"""Planejamento e execução reproduzível da comparação da Etapa 7."""

import argparse
import json
import os
import platform
import re
import subprocess
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from random import Random
from time import perf_counter
from uuid import uuid4

from .agent import EXPERIMENT_PROMPT, JUSTIFICATION_LIMIT, AgentSession
from .dataset import OFFICIAL_PATH, dataset_digest
from .experiment_cases import DETECTOR, LIMITS, case_catalog, detections_for
from .hardware import physical_memory, processor_name
from .loop import propose
from .ollama import AgentConfig, OllamaClient
from .rag import EMBED_MODEL, INDEX, MIN_SCORE, RAG_ERRORS, TOP_K, Embedder, RagSession, digest_json
from .simulator import Simulator

CONFIGURATIONS = {
    "A": {"modelo": False, "mcp": False, "rag": False},
    "B": {"modelo": True, "mcp": False, "rag": False},
    "C": {"modelo": True, "mcp": False, "rag": True},
    "D": {"modelo": True, "mcp": True, "rag": False},
    "E": {"modelo": True, "mcp": True, "rag": True},
}
SEEDS = (42, 43, 44)
ORDER_SEED = 20261127
ROOT = Path("results/etapa7")


@dataclass(frozen=True)
class ExperimentConfig:
    phase: str = "piloto"
    mode: str = "controlada"
    cases: tuple[str, ...] = ()
    configurations: tuple[str, ...] = tuple(CONFIGURATIONS)
    repetitions: int = 1
    max_calls: int = 12
    api: str = AgentConfig.url
    index: Path = INDEX
    excel: Path = OFFICIAL_PATH

    def __post_init__(self):
        if self.phase not in ("piloto", "final", "exploratorio") or self.mode not in ("controlada", "ciclo"):
            raise ValueError("Fase ou modo inválido")
        if type(self.repetitions) is not int or not 1 <= self.repetitions <= len(SEEDS):
            raise ValueError("Use de uma a três repetições")
        if type(self.max_calls) is not int or self.max_calls < 0 or (self.phase == "piloto" and self.max_calls > 12):
            raise ValueError("Limite global inválido. O piloto admite até 12 chamadas")
        if (not self.configurations or not set(self.configurations) <= CONFIGURATIONS.keys()
                or len(set(self.configurations)) != len(self.configurations)):
            raise ValueError("Selecione configurações distintas de A a E")
        AgentConfig(url=self.api)


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@contextmanager
def run_lock(directory):
    """Trava liberada pelo sistema inclusive quando o processo é interrompido."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a+b") as stream:
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("Há outra operação ativa nesta pasta de experimento") from error
        yield


def code_identity():
    package = Path(__file__).resolve().parent
    try:
        result = subprocess.run(["git", "-C", str(package), "rev-parse", "HEAD"],
                                capture_output=True, encoding="utf-8", check=True, timeout=5)
        revision = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        revision = None
    files = {p.name: dataset_digest(p) for p in sorted(package.iterdir()) if p.suffix in (".py", ".json")}
    return {"git": revision, "fontes_sha256": digest_json(files), "arquivos_sha256": files}


def agent_config(seed, api, opportunities=1, mcp=False):
    return AgentConfig(model="qwen2.5:1.5b", url=api, temperature=0, seed=seed, num_ctx=8192, num_predict=512,
                       max_calls=opportunities * (2 if mcp else 1), max_failures=opportunities + 1,
                       selection="todas")


def prepare_simulator(frame, detections, case, first_window):
    simulator = Simulator(frame, detections, case.replay.advance, LIMITS)
    for detection in detections:
        window = detection["janela"]["id"]
        if window >= first_window:
            break
        simulator.apply(propose(detection), origin="preparacao_python", window_id=window)
    return simulator


def build_plan(config, catalog=None):
    catalog = case_catalog(config.phase, config.excel) if catalog is None else catalog
    cases = {case.id: case for case in catalog if not config.cases or case.id in config.cases}
    if not cases or (config.cases and (set(config.cases) != set(cases) or len(config.cases) != len(cases))):
        raise ValueError("Seleção inválida de casos da fase")
    base_order = sorted(config.configurations)
    Random(ORDER_SEED).shuffle(base_order)
    jobs = []
    cases_manifest = {case.id: {**case.manifest(), "entradas": {}} for case in cases.values()}
    for repetition, seed in enumerate(SEEDS[:config.repetitions], 1):
        for i, case in enumerate(cases.values()):
            targets = case.targets if config.mode == "controlada" else (None,)
            for j, target in enumerate(targets):
                frame, detections = detections_for(case, target)
                windows = [target] if target is not None else [d["janela"]["id"] for d in detections]
                if not windows or windows[-1] != detections[-1]["janela"]["id"]:
                    raise ValueError(f"Janela-alvo ausente no caso {case.id}")
                key = str(target) if target is not None else "ciclo"
                if key not in cases_manifest[case.id]["entradas"]:
                    prepared = prepare_simulator(frame, detections, case, windows[0])
                    cases_manifest[case.id]["entradas"][key] = {
                        "janelas": windows, "estado_inicial": prepared.state(),
                        "preparacao_sha256": digest_json(prepared.history()),
                        "primeiro_register": detections[0]["janela"]["registros"][0],
                        "ultimo_register": detections[-1]["janela"]["registros"][-1],
                    }
                offset = (i + repetition - 1 + j) % len(base_order)
                for method in base_order[offset:] + base_order[:offset]:
                    variant = CONFIGURATIONS[method]
                    cap = len(windows) * (1 + int(variant["mcp"])) if variant["modelo"] else 0
                    jobs.append({"id": f"{case.id}-{target or 'ciclo'}-{seed}-{method}", "caso": case.id,
                                 "alvo": target, "janelas": windows, "repeticao": repetition, "seed": seed,
                                 "configuracao": method, "max_chat": cap})
    params = {**asdict(config), "index": str(config.index.resolve()),
              "excel": str(config.excel.resolve()) if config.phase == "exploratorio" else None}
    params = json.loads(json.dumps(params))
    index_hash = dataset_digest(config.index) if config.index.is_file() and any(
        CONFIGURATIONS[m]["rag"] for m in config.configurations) else None
    plan = {"formato": 1, "parametros": params, "codigo": code_identity(),
            "detector": asdict(DETECTOR), "simulador": asdict(LIMITS),
            "inferencia": {"modelo": "qwen2.5:1.5b", "seeds": list(SEEDS[:config.repetitions]),
                           "temperatura": 0, "contexto": 8192, "geracao": 512, "timeout_s": AgentConfig.timeout,
                           "justificativa_max_caracteres": JUSTIFICATION_LIMIT, "prompt": EXPERIMENT_PROMPT,
                           "prompt_sha256": digest_json(EXPERIMENT_PROMPT), "ordem_seed": ORDER_SEED,
                           "mcp_consultas_por_janela": 1, "mcp_timeout_s": 5,
                           "modelo_embeddings": EMBED_MODEL, "top_k": TOP_K, "score_minimo": MIN_SCORE},
            "configuracoes": {m: CONFIGURATIONS[m] for m in config.configurations},
            "indice_arquivo_sha256": index_hash, "casos": list(cases_manifest.values()),
            "execucoes": jobs, "max_chat_planejado": sum(job["max_chat"] for job in jobs)}
    return {**plan, "sha256": digest_json(plan)}


def dependency_versions():
    installed = {}
    for name in ("oran-agentic-lab", "pandas", "matplotlib", "openpyxl", "mcp", "pypdf"):
        try:
            installed[name] = version(name)
        except PackageNotFoundError:
            installed[name] = None
    return installed


def environment(config, client_factory, rag_factory):
    details = {"sistema": platform.platform(), "python": platform.python_version(), "arquitetura": platform.machine(),
               "cpu": processor_name(), "cpus_logicas": os.cpu_count(), "ram_bytes": physical_memory(),
               "dependencias": dependency_versions()}
    variant = [CONFIGURATIONS[m] for m in config.configurations]
    if any(v["modelo"] for v in variant):
        try:
            details["gerador"] = client_factory(agent_config(SEEDS[0], config.api)).metadata()
        except (RAG_ERRORS + (AttributeError, TypeError)) as error:
            if config.phase != "final":
                raise
            details["gerador"] = {"erro": str(error)}
    if any(v["rag"] for v in variant):
        try:
            rag = rag_factory(config)
            details["rag"] = {k: v for k, v in rag.metadata.items() if k != "tempo_abertura_s"}
        except (RAG_ERRORS + (AttributeError, TypeError)) as error:
            if config.phase != "final":
                raise
            details["rag"] = {"erro_indice": str(error)}
            details["embeddings"] = {"erro": str(error)}
            return details
        if config.phase == "final":
            try:
                details["embeddings"] = rag.embedder.identity()
            except (RAG_ERRORS + (AttributeError, TypeError)) as error:
                details["embeddings"] = {"erro": str(error)}
    return details


def preflight_resources(config, plan, resources):
    """Verifica o inventário local e o índice do plano sem fazer inferência."""
    def valid_digest(value):
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

    checks = {}
    if "gerador" in resources:
        model = resources["gerador"]
        service = model.get("ollama")
        checks["ollama"] = {"ok": isinstance(service, str) and bool(service.strip()), "versao": service}
        checks["gerador"] = {"ok": valid_digest(model.get("digest")), "tag": agent_config(SEEDS[0], config.api).model,
                             "digest": model.get("digest"), "erro": model.get("erro")}
    if "rag" in resources:
        embeddings = resources["embeddings"]
        embedding_ok = embeddings.get("modelo") == f"{EMBED_MODEL}:latest" and valid_digest(embeddings.get("digest"))
        checks["embeddings"] = {**embeddings, "ok": embedding_ok}
        rag = resources["rag"]
        try:
            file_hash = dataset_digest(config.index)
        except OSError as error:
            file_hash = None
            file_error = str(error)
        else:
            file_error = None if file_hash == plan.get("indice_arquivo_sha256") else "Arquivo difere do plano"
        indexed = rag.get("indexacao") or {}
        index_ok = (file_error is None and valid_digest(rag.get("indice_sha256")) and not rag.get("erro_indice")
                    and embedding_ok and all(indexed.get(key) == embeddings[key] for key in ("modelo", "digest")))
        checks["indice_rag"] = {"ok": index_ok, "arquivo_sha256": file_hash, "indice_sha256": rag.get("indice_sha256"),
                                 "erro": file_error or rag.get("erro_indice")}
    return checks


def local_rag(config):
    return RagSession(config.index, Embedder(AgentConfig(model=EMBED_MODEL, url=config.api)), TOP_K, MIN_SCORE)


def load_average():
    try:
        return list(os.getloadavg())
    except (AttributeError, OSError):
        return None


class ChatLedger:
    """Reserva e persiste cada tentativa antes de enviar ao serviço local."""

    def __init__(self, directory, cap):
        self.directory = directory
        self.cap = cap
        self.used = len(list(directory.glob("execucoes/*/chat/*-inicio.json")))

    def request(self, client, job_directory, path, payload):
        if path != "/api/chat":
            return client.request(path, payload)
        if self.used >= self.cap:
            raise ValueError("Limite global de chat atingido")
        self.used += 1
        prefix = job_directory / "chat" / f"{self.used:05d}"
        kind = "decisao" if payload["messages"][0]["content"] == EXPERIMENT_PROMPT else "selecao_mcp"
        atomic_json(prefix.with_name(prefix.name + "-inicio.json"),
                    {"tipo": kind, "data": now(), "payload": payload})
        try:
            status, raw = client.request(path, payload)
        except Exception as error:
            atomic_json(prefix.with_name(prefix.name + "-fim.json"), {"data": now(), "erro": str(error)})
            raise
        atomic_json(prefix.with_name(prefix.name + "-fim.json"),
                    {"data": now(), "status": status, "resposta_original": raw})
        return status, raw


class LoggedClient:
    def __init__(self, client, ledger, job_directory):
        self.client = client
        self.ledger = ledger
        self.job_directory = job_directory

    def request(self, path, payload):
        return self.ledger.request(self.client, self.job_directory, path, payload)

    def metadata(self):
        return self.client.metadata()

    def residency(self):
        return self.client.residency()


def execute_job(job, case, config, client_factory, rag_factory, emit, *, resources=None):
    """Executa uma sessão isolada e emite uma decisão auditável por janela avaliada."""
    frame, detections = detections_for(case, job["alvo"])
    simulator = prepare_simulator(frame, detections, case, job["janelas"][0])
    variant = CONFIGURATIONS[job["configuracao"]]
    agent = None
    start = perf_counter()
    catalog = {d["janela"]["id"]: d for d in detections}
    if variant["modelo"]:
        options = agent_config(job["seed"], config.api, len(job["janelas"]), variant["mcp"])
        agent = AgentSession(options, client_factory(options), rag_factory(config) if variant["rag"] else None,
                             experiment=True)
        if resources is not None:
            if agent.metadata != resources["gerador"]:
                raise ValueError("Identidade do gerador mudou em relação ao manifesto")
            if agent.rag is not None:
                identity = {k: v for k, v in agent.rag.metadata.items() if k != "tempo_abertura_s"}
                if identity != resources["rag"]:
                    raise ValueError("Índice ou modelo de embeddings mudou em relação ao manifesto")
    if variant["mcp"]:
        from .mcp_client import MCPWindow
    prepared = simulator.history()
    initial = simulator.state()
    emit("preparacao", {"historico": prepared, "estado_inicial": initial,
                        "residencia": agent.client.residency() if agent else None, "carga": load_average()})
    for window in job["janelas"]:
        step_start = perf_counter()
        before = simulator.state()
        offset = len(simulator.history())
        detection = catalog[window]
        mcp = MCPWindow(simulator, frame, catalog, window, 1, 5) if variant["mcp"] else None
        if agent:
            agent.decide(detection, simulator, propose, mcp)
        else:
            simulator.apply(propose(detection), origin="politica_deterministica", window_id=window)
        emit(f"janela-{window:04d}", {
            "janela": window, "detector": detection, "expectativa": case.expectation(window),
            "estado_anterior": before, "estado_posterior": simulator.state(),
            "historico": simulator.history()[offset:], "agente": agent.decisions[-1] if agent else None,
            "tempo_s": perf_counter() - step_start,
        })
    return {"estado": "concluida", "tempo_s": perf_counter() - start, "carga": load_average(),
            "residencia_final": agent.client.residency() if agent else None,
            "modelo": agent.metadata if agent else None, "rag": agent.rag.metadata if agent and agent.rag else None}


def run_experiment(config, directory, *, authorize_final=False, resume=False,
                   client_factory=OllamaClient, rag_factory=local_rag, catalog=None, on_event=None):
    """Executa ou retoma um plano sem reenviar tentativas já reservadas."""
    if config.phase == "final" and not authorize_final:
        raise ValueError("A bateria final exige autorização explícita após revisão do plano")
    source = case_catalog(config.phase, config.excel) if catalog is None else catalog
    cases = {c.id: c for c in source}
    with run_lock(directory):
        planned = directory / "plano.json"
        if config.phase == "final" and not planned.exists():
            raise ValueError("Salve o plano final nesta pasta antes de autorizar a execução")
        manifest_file = directory / "manifesto.json"
        old = read_json(manifest_file) if manifest_file.exists() else None
        if old is not None and not resume:
            raise ValueError("Execução existente. Use retomada ou uma pasta nova")
        saved_plan = read_json(planned) if planned.exists() else None
        if config.phase == "final":
            if saved_plan.get("codigo") != code_identity():
                raise ValueError("Código ou revisão Git diferente do plano final. Preserve-o e planeje em outra pasta")
            runtime = environment(config, client_factory, rag_factory)
            checks = preflight_resources(config, saved_plan, runtime)
            errors = [name for name, result in checks.items() if not result["ok"]]
            atomic_json(directory / "pre-verificacoes" / f"{uuid4().hex}.json",
                        {"data_utc": now(), "fase": "pre_retomada" if old else "pre_execucao",
                         "plano_sha256": saved_plan.get("sha256"),
                         "estado": "bloqueada" if errors else "aprovada", "verificacoes": checks})
            if errors:
                raise ValueError(f"Pré-verificação da bateria final bloqueada: {', '.join(errors)}. "
                                 "Consulte pre-verificacoes/")
        plan = build_plan(config, source)
        if saved_plan is not None and saved_plan != plan:
            raise ValueError("Plano diferente nesta pasta. Use outro identificador de execução")
        if config.phase != "final":
            runtime = environment(config, client_factory, rag_factory)
        if old is not None and (old["plano_sha256"] != plan["sha256"] or old["recursos"] != runtime):
            raise ValueError("Código, recursos ou parâmetros mudaram. Use uma nova pasta")
        if not planned.exists():
            atomic_json(planned, plan)
        if old is None:
            atomic_json(manifest_file, {"id": uuid4().hex, "inicio_utc": now(), "plano_sha256": plan["sha256"],
                                        "recursos": runtime})
        ledger = ChatLedger(directory, config.max_calls)
        for job in plan["execucoes"]:
            folder = directory / "execucoes" / job["id"]
            end = folder / "resultado.json"
            if end.exists():
                continue
            if any((folder / "chat").glob("*-inicio.json")):
                atomic_json(end, {"estado": "interrompida", "erro": "Tentativas anteriores preservadas"})
                continue
            if job["max_chat"] > config.max_calls - ledger.used:
                break

            def emit(event, payload):
                record = {"evento": event, "data": now(), "execucao": job["id"], **payload}
                atomic_json(folder / "eventos" / f"{event}.json", record)
                if on_event:
                    on_event(record)

            def factory(options):
                return LoggedClient(client_factory(options), ledger, folder)

            try:
                result = execute_job(job, cases[job["caso"]], config, factory, rag_factory, emit, resources=runtime)
            except RAG_ERRORS as error:
                result = {"estado": "falha", "fase_falha": "durante_execucao", "erro": f"{type(error).__name__}: {error}"}
            atomic_json(end, result)
        return {"pasta": str(directory), "chamadas_reservadas": ledger.used, "max_chat": config.max_calls}


def save_plan(config, directory):
    plan = build_plan(config)
    with run_lock(directory):
        path = directory / "plano.json"
        if path.exists() and read_json(path) != plan:
            raise ValueError("Plano diferente nesta pasta")
        if not path.exists():
            atomic_json(path, plan)
    return plan


def main(argv=None):
    from .experiment_report import aggregate, import_reviews

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operacao", choices=("planejar", "executar", "agregar", "importar-avaliacoes"))
    parser.add_argument("--fase", choices=("piloto", "final", "exploratorio"), default="piloto")
    parser.add_argument("--modo", choices=("controlada", "ciclo"), default="controlada")
    parser.add_argument("--casos", nargs="+", default=[])
    parser.add_argument("--configuracoes", nargs="+", choices=tuple(CONFIGURATIONS), default=list(CONFIGURATIONS))
    parser.add_argument("--repeticoes", type=int)
    parser.add_argument("--limite-chamadas", type=int)
    parser.add_argument("--api", default=AgentConfig.url)
    parser.add_argument("--indice", type=Path, default=INDEX)
    parser.add_argument("--excel", type=Path, default=OFFICIAL_PATH)
    parser.add_argument("--saida", type=Path)
    parser.add_argument("--retomar", action="store_true")
    parser.add_argument("--autorizar-final", action="store_true")
    parser.add_argument("--avaliacoes", type=Path)
    parser.add_argument("--avaliador", help="Identificador do avaliador para a importação")
    args = parser.parse_args(argv)
    if (args.operacao in ("agregar", "importar-avaliacoes") or args.retomar) and args.saida is None:
        parser.error("Informe --saida com a pasta do experimento")
    directory = args.saida or ROOT / f"{args.fase}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:6]}"
    try:
        if args.operacao == "agregar":
            result = aggregate(directory)
        elif args.operacao == "importar-avaliacoes":
            if args.avaliacoes is None:
                parser.error("Informe --avaliacoes com o CSV preenchido")
            result = import_reviews(directory, args.avaliacoes, evaluator=args.avaliador)
        else:
            is_final = args.fase == "final"
            limit = args.limite_chamadas if args.limite_chamadas is not None else 108 if is_final else 12
            repetitions = args.repeticoes if args.repeticoes is not None else 3 if is_final else 1
            config = ExperimentConfig(args.fase, args.modo, tuple(args.casos), tuple(args.configuracoes),
                                      repetitions, limit, args.api, args.indice, args.excel)
            if args.operacao == "planejar":
                plan = save_plan(config, directory)
                result = {"pasta": str(directory), "execucoes": len(plan["execucoes"]),
                          "max_chat_planejado": plan["max_chat_planejado"], "limite": limit}
            else:
                result = run_experiment(config, directory, authorize_final=args.autorizar_final, resume=args.retomar)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError) as error:
        parser.exit(2, f"Erro no experimento: {error}\n")


if __name__ == "__main__":
    main()
