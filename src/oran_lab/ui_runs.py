"""Configuração, armazenamento e controle do worker local da interface."""

import os
import re
import subprocess
import sys
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http.client import HTTPException
from importlib.metadata import version
from pathlib import Path
from time import sleep
from uuid import uuid4

from .dataset import OFFICIAL_PATH, dataset_digest
from .detector import DetectorConfig
from .experiment import atomic_json, code_identity, dependency_versions, now, read_json, run_lock
from .experiment_cases import FINAL_CASES, PILOT_CASES
from .loop import _synthetic_frame, run_loop, write_results
from .ollama import AgentConfig, OllamaClient, strict_json
from .rag import EMBED_MODEL, Embedder, RagSession, digest_json, model_tag
from .replay import ReplayConfig, load_kpm
from .simulator import Limits
from .ui_resources import SOURCE_ID, custom_source, local_path

ARCHITECTURES = {"A": "Python determinístico", "B": "LLM", "C": "LLM + RAG",
                 "D": "LLM + MCP", "E": "LLM + MCP + RAG"}
SOURCES = {"demonstracao": "Sintético · demonstração do laboratório",
           "oficial": "Excel oficial · KPMs históricos",
           **{case.id: f"Sintético · {case.id.replace('-', ' ')}" for case in (*FINAL_CASES, *PILOT_CASES)}}
TERMINAL = {"concluida", "interrompida", "falha"}
ID = re.compile(r"[0-9a-f]{32}")
FILENAME = re.compile(r"[a-zA-Z0-9_.-]+\.json")


@dataclass(frozen=True)
class RunConfig:
    architecture: str = "A"
    source: str = "demonstracao"
    replay: ReplayConfig = field(default_factory=lambda: ReplayConfig(2))
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    limits: Limits = field(default_factory=Limits)
    agent: AgentConfig | None = None
    mcp_reads: int | None = None
    mcp_timeout: float = 5
    index: str | None = None
    top_k: int = 2
    min_score: float = 0.35
    start_paused: bool = False

    def __post_init__(self):
        if self.architecture not in ARCHITECTURES or (self.source not in SOURCES and not SOURCE_ID.fullmatch(self.source)):
            raise ValueError("Arquitetura ou fonte desconhecida.")
        if (self.agent is not None) != (self.architecture != "A"):
            raise ValueError("Selecione o gerador apenas para as arquiteturas B–E.")
        if (self.mcp_reads is not None) != (self.architecture in "DE"):
            raise ValueError("MCP deve estar configurado somente em D ou E.")
        if (self.index is not None) != (self.architecture in "CE"):
            raise ValueError("Selecione um índice RAG para C ou E.")
        if self.mcp_reads is not None and (type(self.mcp_reads) is not int or not 1 <= self.mcp_reads <= 4):
            raise ValueError("MCP admite de 1 a 4 consultas por janela.")
        if self.mcp_reads is not None and not 0 < self.mcp_timeout <= 120:
            raise ValueError("Timeout MCP deve ficar entre 0 e 120 segundos.")
        if type(self.top_k) is not int or not 1 <= self.top_k <= 8 or not -1 <= self.min_score <= 1:
            raise ValueError("Top-K deve ficar entre 1 e 8, e cosseno entre -1 e 1.")
        if self.index is not None and not FILENAME.fullmatch(self.index):
            raise ValueError("Selecione um índice JSON da pasta data/rag.")
        if self.replay.advance < self.limits.min_inspection_stride:
            raise ValueError("O avanço do replay precisa respeitar o mínimo do simulador.")
        if self.agent and self.agent.num_ctx <= self.agent.num_predict + 256:
            raise ValueError("O contexto deve comportar geração, formatação e evidências.")

    @classmethod
    def from_dict(cls, data):
        return cls(**{**data, "replay": ReplayConfig(**data["replay"]), "detector": DetectorConfig(**data["detector"]),
                      "limits": Limits(**data["limits"]),
                      "agent": AgentConfig(**data["agent"]) if data["agent"] else None})


def data_source(config, workspace):
    if SOURCE_ID.fullmatch(config.source):
        return custom_source(workspace, config.source)
    if config.source == "oficial":
        from .data import OFFICIAL_SHA256

        path = local_path(workspace, OFFICIAL_PATH)
        checksum, frame = load_kpm(path)
        if checksum != OFFICIAL_SHA256:
            raise ValueError("A revisão do Excel diverge do dataset oficial.")
        return frame, {"tipo": "oficial", "arquivo": path.name, "sha256": checksum}
    if config.source == "demonstracao":
        return _synthetic_frame()
    case = next(case for case in (*FINAL_CASES, *PILOT_CASES) if case.id == config.source)
    return case.frame(), {"tipo": "sintetico", "cenario": case.id, "sha256": digest_json(case.records)}


def available_indices(workspace):
    parent = local_path(workspace, Path("data/rag"))
    return sorted(p.name for p in parent.glob("*.json")
                  if FILENAME.fullmatch(p.name) and p.is_file() and not p.is_symlink())


def model_details(client, tag):
    status, raw = client.request("/api/show", {"model": tag})
    if status != 200:
        raise ValueError(f"Ollama não confirmou o modelo {tag} (HTTP {status}).")
    info = strict_json(raw)
    return info if isinstance(info, dict) else {}


def capabilities(client, tag):
    return model_details(client, tag).get("capabilities", [])


def discover_models(client=None):
    client = client if client is not None else OllamaClient(AgentConfig(timeout=3))
    service = client.info("/api/version").get("version")
    if not service:
        raise ValueError("O serviço Ollama local está indisponível.")
    tags = client.info("/api/tags").get("models")
    if not isinstance(tags, list):
        raise ValueError("O Ollama não forneceu o inventário de modelos.")
    generators = []
    for item in tags:
        name = item.get("name")
        if (name and not name.endswith((":cloud", "-cloud")) and not item.get("remote_host")
                and not item.get("remote_model") and "completion" in capabilities(client, name)):
            generators.append(name)
    return sorted(set(generators)), service


def prepare(config, workspace, *, client_factory=OllamaClient, rag_factory=RagSession):
    frame, source = data_source(config, workspace)
    if frame.empty:
        raise ValueError("A fonte está vazia.")
    metadata = {"fonte": source}
    client = rag = None
    if config.agent:
        client = client_factory(config.agent)
        info = client.metadata()
        if not info.get("ollama"):
            raise ValueError("O serviço Ollama local está indisponível.")
        if not re.fullmatch("[a-f0-9]{64}", info.get("digest") or ""):
            raise ValueError("O modelo gerador selecionado está indisponível ou sem digest válido.")
        details = model_details(client, config.agent.model)
        if "completion" not in details.get("capabilities", []):
            raise ValueError("O modelo selecionado não oferece geração de texto.")
        model_info = details.get("model_info") or {}
        family = details.get("details") or {}
        metadata["gerador"] = {"tag": model_tag(config.agent.model), **info,
                               "arquitetura_modelo": model_info.get("general.architecture", family.get("family")),
                               "parametros_modelo": model_info.get("general.parameter_count", family.get("parameter_size"))}
    if config.mcp_reads is not None:
        from .mcp_client import MCPWindow  # valida a disponibilidade do cliente e SDK

        metadata["mcp"] = {"sdk": version("mcp"), "transporte": "memoria"}
    if config.index:
        index_path = local_path(workspace, Path("data/rag") / config.index)
        # O índice informa o modelo de embeddings. A sessão verifica tag e digest no Ollama.
        from .rag import load_index

        stored = load_index(index_path)
        embedding = stored["metadados"].get("modelo", EMBED_MODEL)
        agent_config = AgentConfig(model=embedding, url=config.agent.url, timeout=config.agent.timeout)
        rag = rag_factory(index_path, Embedder(agent_config, client_factory(agent_config)), config.top_k, config.min_score)
        if rag.error:
            raise ValueError(f"Índice ou modelo de embeddings indisponível. {rag.error}")
        metadata["rag"] = {k: v for k, v in rag.metadata.items() if k != "tempo_abertura_s"}
        metadata["rag"]["arquivo_sha256"] = dataset_digest(index_path)
    return frame, source, metadata, client, rag


def runs_root(workspace):
    return local_path(workspace, Path("results/ui"))


def run_path(workspace, run_id):
    if not ID.fullmatch(run_id):
        raise ValueError("Identificador de execução inválido.")
    return local_path(workspace, Path("results/ui") / run_id)


def status(directory):
    return read_snapshot(directory / "status.json")


def read_snapshot(path):
    for attempt in range(20):
        try:
            return read_json(path)
        except PermissionError:
            if attempt == 19:
                raise
            sleep(0.025)


def publish(path, payload):
    # No Windows uma leitura concorrente pode bloquear brevemente a substituição do arquivo.
    for attempt in range(20):
        try:
            atomic_json(path, payload)
            return
        except PermissionError:
            if attempt == 19:
                raise
            sleep(0.05)


def set_status(directory, state, **payload):
    data = {"estado": state, **payload, "data_utc": now()}
    publish(directory / "status.json", data)
    return data


def current_run(workspace):
    root = runs_root(workspace)
    marker = root / "atual.json"
    return read_snapshot(marker)["id"] if marker.is_file() else None


def recorded_time(value):
    """Interpreta somente timestamps com fuso explicitamente registrado."""
    if isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value)
            if stamp.utcoffset() is not None:
                return stamp
        except ValueError:
            pass
    return None


def manifest_order(manifest):
    return recorded_time(manifest.get("inicio_utc")) or datetime.min.replace(tzinfo=timezone.utc)


def list_runs(workspace):
    root = runs_root(workspace)
    manifests = [p for p in root.glob("*/manifesto.json")
                 if ID.fullmatch(p.parent.name) and not p.parent.is_symlink() and not p.is_symlink()]
    return sorted((read_json(p) for p in manifests), key=manifest_order, reverse=True)


class Journal:
    def __init__(self, directory):
        self.directory = directory
        self.seq = 0

    def __call__(self, component, state, window, payload):
        self.seq += 1
        atomic_json(self.directory / "eventos" / f"{self.seq:07d}.json",
                    {"seq": self.seq, "componente": component, "estado": state,
                     "janela": window, "dados": payload, "data_utc": now()})


def read_events(directory, after=0):
    return [read_json(p) for p in sorted((directory / "eventos").glob("[0-9]*.json")) if int(p.stem) > after]


def save_partial(directory):
    events = read_events(directory)
    decisions = [e for e in events if e["componente"] == "janela" and e["estado"] == "concluida"]
    if decisions:
        final_window = decisions[-1]["janela"]
        detections = [e["dados"]["deteccao"] for e in events if e["componente"] == "detector"
                      and e["estado"] == "concluida" and e["janela"] <= final_window]
        atomic_json(directory / "parcial.json", {"deteccoes": detections, "janelas": decisions,
                    "estado_final": decisions[-1]["dados"]["estado_simulador"]})


def worker_alive(workspace):
    try:
        with run_lock(runs_root(workspace) / "worker"):
            return False
    except ValueError:
        return True


def active_experiment(workspace):
    root = runs_root(workspace)
    marker = root / "experimento-atual.json"
    if not marker.is_file():
        return None
    run_id = read_snapshot(marker)["id"]
    if not ID.fullmatch(run_id):
        raise ValueError("Identificador experimental inválido.")
    directory = local_path(workspace, Path("results/ui/experimentos") / run_id)
    snapshot = status(directory)
    if snapshot["estado"] in TERMINAL:
        return None
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(snapshot["data_utc"])).total_seconds()
    if worker_alive(workspace) or (snapshot["estado"] == "iniciando" and elapsed < 60):
        return run_id
    set_status(directory, "falha", **{k: v for k, v in snapshot.items() if k not in ("estado", "data_utc", "erro")},
               erro="O worker experimental terminou sem publicar o estado final.")
    return None


def active_run(workspace):
    if current_run(workspace) is None:
        return None
    with await_lock(runs_root(workspace)):
        return _active_run(workspace)


def _active_run(workspace):
    run_id = current_run(workspace)
    if run_id is None:
        return None
    directory = run_path(workspace, run_id)
    snapshot = status(directory)
    if snapshot["estado"] in TERMINAL:
        return None
    if worker_alive(workspace):
        return run_id
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(snapshot["data_utc"])).total_seconds()
    if snapshot["estado"] == "iniciando" and elapsed < 60:
        return run_id
    save_partial(directory)
    set_status(directory, "falha", erro="Worker encerrado antes de publicar o término.")
    return None


def spawn_worker(workspace, run_id, log, *, module="oran_lab.ui_runs"):
    command = [sys.executable, "-m", module, run_id]
    flags = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
             if os.name == "nt" else {"start_new_session": True})
    with log.open("ab") as stream:
        return subprocess.Popen(command, cwd=workspace, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"}, **flags)


def start_run(config, workspace, *, request_id=None, spawn=spawn_worker, prepare_run=prepare):
    run_id = request_id or uuid4().hex
    directory = run_path(workspace, run_id)
    canonical = asdict(config)
    with run_lock(runs_root(workspace)):
        if (directory / "manifesto.json").exists():
            if read_json(directory / "manifesto.json")["configuracao"] != canonical:
                raise ValueError("Este identificador já possui configuração imutável.")
            return run_id
        if _active_run(workspace) or active_experiment(workspace) or worker_alive(workspace):
            raise ValueError("Já existe uma execução ou manutenção ativa.")
        _, _, resources, _, _ = prepare_run(config, workspace)
        atomic_json(directory / "manifesto.json", {"id": run_id, "inicio_utc": now(), "codigo": code_identity(),
                    "versoes": {**dependency_versions(), "python": sys.version.split()[0],
                                "streamlit": optional_version("streamlit"), "plotly": optional_version("plotly")},
                    "configuracao": canonical, "configuracao_sha256": digest_json(canonical), "recursos": resources})
        atomic_json(directory / "controle.json", {"modo": "pausar" if config.start_paused else "continuar"})
        set_status(directory, "iniciando")
        publish(runs_root(workspace) / "atual.json", {"id": run_id})
        try:
            spawn(workspace, run_id, directory / "worker.log")
        except OSError as error:
            set_status(directory, "falha", erro=str(error))
            raise
    return run_id


def optional_version(name):
    from importlib.metadata import PackageNotFoundError

    try:
        return version(name)
    except PackageNotFoundError:
        return None


def send_command(directory, command):
    if command not in ("pausar", "continuar", "avancar", "interromper"):
        raise ValueError("Comando de execução desconhecido.")
    with await_lock(directory / "controle"):
        state = status(directory)["estado"]
        current = read_json(directory / "controle.json")["modo"]
        if state in TERMINAL or current == "interromper":
            raise ValueError("A execução já encerrou ou está com interrupção solicitada.")
        if command == "avancar" and (state != "pausada" or current != "pausar"):
            raise ValueError("Avance apenas a partir de uma execução pausada.")
        publish(directory / "controle.json", {"modo": command})


@contextmanager
def await_lock(directory):
    with ExitStack() as stack:
        for attempt in range(40):
            try:
                stack.enter_context(run_lock(directory))
            except ValueError:
                if attempt == 39:
                    raise
                sleep(0.025)
            else:
                break
        yield


class WindowGate:
    def __init__(self, directory, wait=sleep):
        self.directory = directory
        self.wait = wait
        self.stopped = False

    def __call__(self, window, total):
        if window > 1:
            self.wait(0.25)
        while True:
            with await_lock(self.directory / "controle"):
                mode = read_json(self.directory / "controle.json")["modo"]
                if mode == "interromper":
                    self.stopped = True
                    return False
                if mode != "pausar":
                    if mode == "avancar":
                        publish(self.directory / "controle.json", {"modo": "pausar"})
                    set_status(self.directory, "executando", janela=window, total=total)
                    return True
                if status(self.directory)["estado"] != "pausada":
                    set_status(self.directory, "pausada", proxima_janela=window, total=total)
            self.wait(0.15)


def run_worker(workspace, run_id, *, prepare_run=prepare, wait=sleep):
    directory = run_path(workspace, run_id)
    with run_lock(runs_root(workspace) / "worker"):
        with await_lock(runs_root(workspace)):
            if current_run(workspace) != run_id or status(directory)["estado"] != "iniciando":
                return
            set_status(directory, "preparando")
        journal = Journal(directory)
        try:
            journal("worker", "iniciada", None, {})
            manifest = read_json(directory / "manifesto.json")
            config = RunConfig.from_dict(manifest["configuracao"])
            if digest_json(asdict(config)) != manifest["configuracao_sha256"]:
                raise ValueError("A configuração gravada foi alterada.")
            if code_identity() != manifest["codigo"]:
                raise ValueError("A revisão do código mudou desde a configuração.")
            frame, source, resources, client, rag = prepare_run(config, workspace)
            if resources != manifest["recursos"]:
                raise ValueError("A identidade das fontes, dos modelos ou do índice mudou.")
            gate = WindowGate(directory, wait)
            result = run_loop(frame, source, config.replay, config.detector, config.limits, agent_config=config.agent,
                              client=client, rag=rag, mcp_reads=config.mcp_reads, mcp_timeout=config.mcp_timeout,
                              on_event=journal, before_window=gate)
            write_results(result, directory)
            state = "interrompida" if gate.stopped else "concluida"
            count = len(result["deteccoes"])
            set_status(directory, state, janelas_concluidas=count)
            journal("worker", state, None, {"janelas_concluidas": count})
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"
            journal("worker", "falha", None, {"erro": reason})
            save_partial(directory)
            set_status(directory, "falha", erro=reason)


if __name__ == "__main__":
    run_worker(Path.cwd(), sys.argv[1])
