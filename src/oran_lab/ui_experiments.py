"""Comparações configuráveis em espaço próprio, com o núcleo experimental da Etapa 7."""

from dataclasses import asdict, dataclass, replace
from itertools import islice
from pathlib import Path
from random import Random
import sys
from time import perf_counter
from uuid import uuid4

from .agent import AgentSession
from .detector import detect
from .experiment import ChatLedger, LoggedClient, code_identity, dependency_versions, load_average, now, read_json, run_lock
from .experiment_report import aggregate
from .loop import propose
from .rag import digest_json
from .simulator import NO_ACTION, REGISTER_ALERT, Simulator
from .ui_runs import (ARCHITECTURES, ID, RunConfig, _active_run, active_experiment, await_lock,
                      data_source, local_path, prepare, publish, runs_root, set_status, spawn_worker, status, worker_alive)


@dataclass(frozen=True)
class Comparison:
    template: RunConfig
    sources: tuple[str, ...]
    treatments: tuple[str, ...]
    seeds: tuple[int, ...]
    repetitions: int = 1
    max_chat: int = 12
    mode: str = "controlada"
    target: int = 1
    purpose: str = "comparacao"

    def __post_init__(self):
        if (not self.sources or len(set(self.sources)) != len(self.sources) or len(self.sources) > 12
                or not self.treatments or len(set(self.treatments)) != len(self.treatments)
                or set(self.treatments) - ARCHITECTURES.keys() or not self.seeds or len(set(self.seeds)) != len(self.seeds)
                or any(type(n) is not int or not -(2**31) <= n < 2**31 for n in self.seeds)
                or type(self.repetitions) is not int or not 1 <= self.repetitions <= 20
                or type(self.max_chat) is not int or not 0 <= self.max_chat <= 2000
                or self.mode not in ("controlada", "ciclo_completo") or self.purpose not in ("comparacao", "exploracao")
                or type(self.target) is not int or self.target < 1
                or len(self.sources) * len(self.treatments) * len(self.seeds) * self.repetitions > 500):
            raise ValueError("Parâmetros inválidos ou comparação acima do limite de 500 sessões.")
        if set(self.treatments) - {"A"} and self.template.agent is None:
            raise ValueError("Escolha o gerador comum aos tratamentos B–E.")
        if set(self.treatments) & {"C", "E"} and not self.template.index:
            raise ValueError("Escolha um índice comum aos tratamentos com RAG.")
        if set(self.treatments) & {"D", "E"} and not self.template.mcp_reads:
            raise ValueError("Defina as condições MCP.")

    @classmethod
    def from_dict(cls, data):
        return cls(**{**data, "template": RunConfig.from_dict(data["template"]),
                      **{key: tuple(data[key]) for key in ("sources", "treatments", "seeds")}})


def treatment(config, source, method, seed, budget):
    template = config.template
    return replace(template, architecture=method, source=source, start_paused=False,
                   agent=None if method == "A" else replace(template.agent, seed=seed, selection="todas",
                                                           max_calls=budget, max_failures=budget + 1),
                   mcp_reads=template.mcp_reads if method in "DE" else None,
                   index=template.index if method in "CE" else None)


def experiment_path(workspace, identifier):
    if not ID.fullmatch(identifier):
        raise ValueError("Identificador experimental inválido.")
    return local_path(workspace, Path("results/ui/experimentos") / identifier)


def list_experiments(workspace):
    parent = local_path(workspace, Path("results/ui/experimentos"))
    return sorted((read_json(experiment_path(workspace, path.parent.name) / path.name)
                   for path in parent.glob("*/manifesto.json") if ID.fullmatch(path.parent.name)),
                  key=lambda item: item["inicio_utc"], reverse=True)


def window_offsets(detection):
    return detection["janela"]["ultima_linha_excel"] - 1


def prepare_target(frame, detections, config, target):
    simulator = Simulator(frame, detections, config.replay.advance, config.limits)
    for item in detections:
        number = item["janela"]["id"]
        if number >= target:
            break
        simulator.apply(propose(item), origin="preparacao_python", window_id=number)
    return simulator


def collect_detections(frame, config, last=None):
    sequence = detect(frame, config.replay, config.detector)
    return list(sequence if last is None else islice(sequence, last))


def plan_comparison(config, workspace, *, source_loader=data_source):
    sources, jobs = {}, []
    for source in config.sources:
        common = replace(config.template, source=source)
        frame, metadata = source_loader(common, workspace)
        if len(frame) > 100000:
            raise ValueError("A fonte excede o limite de 100.000 registros por comparação.")
        detections = collect_detections(frame, common, config.target if config.mode == "controlada" else None)
        if not detections or (config.mode == "controlada" and config.target > len(detections)):
            raise ValueError(f"A fonte {source} não contém a janela-alvo solicitada.")
        if config.mode == "controlada":
            windows = [config.target]
            frame = frame.iloc[:window_offsets(detections[-1])]
        else:
            windows = list(range(1, len(detections) + 1))
        initial = prepare_target(frame, detections, common, windows[0]).state()
        sources[source] = {"origem": metadata, "evidencia_sha256": digest_json(detections),
                           "estado_inicial": initial, "janelas": windows}
        for repeat in range(1, config.repetitions + 1):
            for seed in config.seeds:
                for method in config.treatments:
                    budget = len(windows) * (0 if method == "A" else 2 if method in "DE" else 1)
                    jobs.append({"id": f"sessao-{len(jobs) + 1:04d}", "caso": source, "configuracao": method,
                                 "seed": seed, "repeticao": repeat, "janelas": windows, "max_chat": budget,
                                 "tratamento": asdict(treatment(config, source, method, seed, budget))})
    Random(42).shuffle(jobs)
    plan = {"versao": 1, "codigo": code_identity(), "configuracao": asdict(config), "fontes": sources,
            "execucoes": jobs, "n_sessoes": len(jobs), "n_oportunidades": sum(len(job["janelas"]) for job in jobs),
            "max_chat": sum(job["max_chat"] for job in jobs), "ordem_seed": 42}
    # Normalize tuples to the JSON representation before comparison with persisted manifests.
    plan["configuracao"].update(sources=list(config.sources), treatments=list(config.treatments), seeds=list(config.seeds))
    return {**plan, "sha256": digest_json(plan)}


def preflight(plan, workspace, prepare_run=prepare):
    resources = {}
    for job in plan["execucoes"]:
        key = f"{job['caso']}/{job['configuracao']}"
        if key not in resources:
            resources[key] = prepare_run(RunConfig.from_dict(job["tratamento"]), workspace)[2]
        if resources[key]["fonte"] != plan["fontes"][job["caso"]]["origem"]:
            raise ValueError("A origem mudou desde o planejamento.")
    generators = {entry["gerador"]["digest"] for entry in resources.values() if "gerador" in entry}
    indices = {entry["rag"]["arquivo_sha256"] for entry in resources.values() if "rag" in entry}
    if len(generators) > 1 or len(indices) > 1:
        raise ValueError("Os recursos comuns mudaram durante a pré-verificação.")
    return resources


def spawn_experiment(workspace, identifier, log):
    return spawn_worker(workspace, identifier, log, module="oran_lab.ui_experiments")


def start_comparison(plan, workspace, *, confirmed=False, request_id=None, spawn=spawn_experiment, prepare_run=prepare):
    if not confirmed:
        raise ValueError("Confirme a bateria antes de iniciar.")
    config = Comparison.from_dict(plan["configuracao"])
    if plan_comparison(config, workspace) != plan:
        raise ValueError("O plano mudou. Gere uma nova prévia.")
    if plan["max_chat"] > config.max_chat:
        raise ValueError("O teto do plano excede o orçamento autorizado.")
    identifier = request_id or uuid4().hex
    directory = experiment_path(workspace, identifier)
    root = runs_root(workspace)
    with run_lock(root):
        if (directory / "manifesto.json").is_file():
            if read_json(directory / "manifesto.json")["plano_sha256"] != plan["sha256"]:
                raise ValueError("Há outro plano vinculado a esse identificador.")
            return identifier
        if _active_run(workspace) or active_experiment(workspace) or worker_alive(workspace):
            raise ValueError("Já existe uma execução ou manutenção ativa.")
        resources = preflight(plan, workspace, prepare_run)
        publish(directory / "plano.json", plan)
        publish(directory / "manifesto.json", {"id": identifier, "plano_sha256": plan["sha256"], "inicio_utc": now(),
                                               "versoes": dependency_versions(), "recursos": resources})
        set_status(directory, "iniciando", concluidas=0, falhas=0, total=plan["n_sessoes"], chat=0)
        publish(root / "experimento-atual.json", {"id": identifier})
        try:
            spawn(workspace, identifier, directory / "worker.log")
        except OSError as error:
            set_status(directory, "falha", erro=str(error))
            raise
    return identifier


def expectation(source, window):
    action = source.get("expectativas_declaradas", {}).get(str(window))
    if action in (REGISTER_ALERT, NO_ACTION):
        return {"acao": action, "parametros": {"evento_id": f"alerta-{window}"} if action == REGISTER_ALERT else {}}
    return None


def execute_session(job, workspace, plan, resources, folder, ledger, prepare_run):
    config = RunConfig.from_dict(job["tratamento"])
    frame, source, observed, client, rag = prepare_run(config, workspace)
    if observed != resources:
        raise ValueError("Os recursos mudaram desde a pré-verificação.")
    windows = job["janelas"]
    detections = collect_detections(frame, config, windows[-1])
    if digest_json(detections) != plan["fontes"][job["caso"]]["evidencia_sha256"]:
        raise ValueError("A evidência planejada mudou.")
    frame = frame.iloc[:window_offsets(detections[-1])]
    simulator = prepare_target(frame, detections, config, windows[0])
    initial = simulator.state()
    if initial != plan["fontes"][job["caso"]]["estado_inicial"]:
        raise ValueError("O estado inicial preparado diverge do plano.")
    agent = AgentSession(config.agent, LoggedClient(client, ledger, folder), rag, experiment=True) if client else None
    publish(folder / "eventos/preparacao.json", {"estado_inicial": initial, "historico": simulator.history(),
                                               "residencia": agent.client.residency() if agent else None})
    catalog = {d["janela"]["id"]: d for d in detections}
    for number in windows:
        start = perf_counter()
        detection = catalog[number]
        before = simulator.state()
        offset = len(simulator.history())
        mcp = None
        if config.mcp_reads:
            from .mcp_client import MCPWindow

            visible = {key: value for key, value in catalog.items() if key <= number}
            mcp = MCPWindow(simulator, frame.iloc[:window_offsets(detection)], visible, number,
                            config.mcp_reads, config.mcp_timeout)
        if agent:
            agent.decide(detection, simulator, propose, mcp)
        else:
            simulator.apply(propose(detection), origin="politica_deterministica", window_id=number)
        publish(folder / "eventos" / f"janela-{number:04d}.json",
                {"janela": number, "detector": detection, "estado_anterior": before, "estado_posterior": simulator.state(),
                 "historico": simulator.history()[offset:], "agente": agent.decisions[-1] if agent else None,
                 "expectativa": expectation(source, number), "tempo_s": perf_counter() - start})
    return {"estado": "concluida", "residencia_final": agent.client.residency() if agent else None, "carga": load_average()}


def run_worker(workspace, identifier, *, prepare_run=prepare, report=aggregate):
    directory = experiment_path(workspace, identifier)
    root = runs_root(workspace)
    with run_lock(root / "worker"):
        with await_lock(root):
            if status(directory)["estado"] != "iniciando":
                return
            marker = read_json(root / "experimento-atual.json")
            if marker["id"] != identifier:
                return
            set_status(directory, "preparando")
        progress = {}
        try:
            plan = read_json(directory / "plano.json")
            manifest = read_json(directory / "manifesto.json")
            config = Comparison.from_dict(plan["configuracao"])
            if not (plan["sha256"] == manifest["plano_sha256"] == plan_comparison(config, workspace)["sha256"]
                    == digest_json({key: value for key, value in plan.items() if key != "sha256"})):
                raise ValueError("O plano congelado ou suas dependências foram alterados.")
            ledger = ChatLedger(directory, config.max_chat)
            progress.update(concluidas=0, falhas=0, total=plan["n_sessoes"], chat=ledger.used)
            set_status(directory, "executando", **progress)
            for job in plan["execucoes"]:
                folder = directory / "execucoes" / job["id"]
                try:
                    result = execute_session(job, workspace, plan, manifest["recursos"][f"{job['caso']}/{job['configuracao']}"],
                                             folder, ledger, prepare_run)
                except Exception as error:
                    result = {"estado": "falha", "fase_falha": "durante_execucao", "erro": f"{type(error).__name__}: {error}"}
                publish(folder / "resultado.json", result)
                progress["concluidas" if result["estado"] == "concluida" else "falhas"] += 1
                progress["chat"] = ledger.used
                set_status(directory, "executando", **progress)
            report(directory)
            set_status(directory, "concluida", **progress)
        except Exception as error:
            set_status(directory, "falha", erro=f"{type(error).__name__}: {error}", **progress)


if __name__ == "__main__":
    run_worker(Path.cwd(), sys.argv[1])
