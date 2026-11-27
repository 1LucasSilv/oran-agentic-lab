"""Controle operacional com dados sintéticos e clients Ollama injetáveis."""

import json
from dataclasses import replace

import pytest

from oran_lab.detector import PRB, THROUGHPUT
from oran_lab import ui_runs
from oran_lab.experiment import read_json
from oran_lab.loop import _synthetic_frame, run_loop
from oran_lab.ollama import AgentConfig
from oran_lab.replay import ReplayConfig
from oran_lab.simulator import Limits
from oran_lab.ui_runs import (
    RunConfig, WindowGate, active_run, discover_models, prepare, read_events, run_path, run_worker, send_command,
    start_run, status,
)


class Client:
    def __init__(self, *, available=True, target=1):
        self.available = available
        self.target = target
        self.chat = []

    def info(self, path):
        if path == "/api/version":
            return {"version": "fixture"} if self.available else {}
        return {"models": [{"name": "gerador:latest"}, {"name": "vetor:latest"},
                           {"name": "remoto:cloud", "remote_host": "fixture"}]}

    def metadata(self):
        return {"ollama": "fixture" if self.available else None, "digest": "a" * 64}

    def residency(self):
        return {}

    def request(self, path, payload):
        if path == "/api/show":
            return 200, json.dumps({"capabilities": ["embedding" if payload["model"] == "vetor:latest"
                                                      else "completion"]})
        self.chat.append(json.loads(payload["messages"][1]["content"]))
        if "ferramentas" in self.chat[-1]:
            obj = {"ferramenta": "consultar_janela", "parametros": {"janela_id": self.target}}
        else:
            obj = {"acao": "nenhuma_acao", "parametros": {}, "justificativa": "Fixture sintética."}
        return 200, json.dumps({"done": True, "message": {"role": "assistant", "content": json.dumps(obj)}})


def test_model_inventory_and_configuration_validation(tmp_path):
    assert discover_models(Client()) == (["gerador:latest"], "fixture")
    with pytest.raises(ValueError, match="indisponível"):
        discover_models(Client(available=False))
    agent = AgentConfig(model="gerador:latest")
    assert RunConfig.from_dict({"architecture": "E", "source": "demonstracao",
                               "replay": {"size": 2}, "detector": {}, "limits": {},
                               "agent": {"model": "gerador:latest"}, "mcp_reads": 1, "index": "indice.json"}).agent == agent
    for kwargs in (dict(architecture="B"), dict(architecture="D", agent=agent, mcp_reads=5),
                   dict(architecture="C", agent=agent, index="../indice.json"),
                   dict(replay=ReplayConfig(2), limits=Limits(min_inspection_stride=3))):
        with pytest.raises(ValueError):
            RunConfig(**kwargs)
    with pytest.raises(ValueError, match="indisponível"):
        prepare(RunConfig("B", agent=agent), tmp_path, client_factory=lambda _: Client(available=False))
    with pytest.raises(FileNotFoundError):
        prepare(RunConfig("C", agent=agent, index="indice.json"), tmp_path, client_factory=lambda _: Client())
    with pytest.raises(FileNotFoundError):
        prepare(RunConfig(source="oficial"), tmp_path)


def test_start_deduplicates_reruns_and_preserves_separate_results(tmp_path):
    outputs = tmp_path / "results" / "etapa7"
    outputs.mkdir(parents=True)
    prior = outputs / "plano.json"
    prior.write_bytes(b"preserve")
    launches = []
    config = RunConfig()
    run_id = "a" * 32
    spawn = lambda *args: launches.append(args)
    assert start_run(config, tmp_path, request_id=run_id, spawn=spawn) == run_id
    assert start_run(config, tmp_path, request_id=run_id, spawn=spawn) == run_id
    assert len(launches) == 1 and active_run(tmp_path) == run_id
    with pytest.raises(ValueError, match="ativa"):
        start_run(config, tmp_path, spawn=spawn)
    with pytest.raises(ValueError, match="imutável"):
        start_run(replace(config, start_paused=True), tmp_path, request_id=run_id, spawn=spawn)
    run_worker(tmp_path, run_id, wait=lambda _: None)
    folder = run_path(tmp_path, run_id)
    events = read_events(folder)
    assert status(folder)["estado"] == "concluida" and len(read_json(folder / "resultados.json")["deteccoes"]) == 8
    assert any(e["componente"] == "validacao" for e in events)
    assert any(e["componente"] == "execucao" and e["estado"] == "concluida" for e in events)
    assert prior.read_bytes() == b"preserve"
    assert read_events(folder, after=events[-2]["seq"]) == events[-1:]
    run_worker(tmp_path, run_id, wait=lambda _: None)
    assert read_events(folder) == events


def test_paused_worker_steps_then_resumes_pauses_and_stops(tmp_path):
    config = RunConfig(start_paused=True)
    run_id = start_run(config, tmp_path, spawn=lambda *args: None)
    folder = run_path(tmp_path, run_id)

    def control(_):
        snap = status(folder)
        if snap["estado"] != "pausada":
            return
        window = snap["proxima_janela"]
        started = [e for e in read_events(folder) if e["componente"] == "replay" and e["estado"] == "concluida"]
        assert len(started) == window - 1
        send_command(folder, "avancar" if window == 1 else "interromper")

    run_worker(tmp_path, run_id, wait=control)
    assert status(folder)["estado"] == "interrompida"
    assert len(read_json(folder / "resultados.json")["deteccoes"]) == 1
    assert all(e["janela"] in (None, 1) for e in read_events(folder))
    assert active_run(tmp_path) is None
    with pytest.raises(ValueError, match="encerrou"):
        send_command(folder, "continuar")


def test_gate_continue_after_pause(tmp_path):
    run_id = start_run(RunConfig(start_paused=True), tmp_path, spawn=lambda *args: None)
    folder = run_path(tmp_path, run_id)
    gate = WindowGate(folder, wait=lambda _: send_command(folder, "continuar"))
    assert gate(1, 2) and status(folder)["estado"] == "executando"
    send_command(folder, "pausar")
    assert gate(2, 2) and status(folder)["janela"] == 2


def test_status_publication_retries_a_transient_reader_conflict(tmp_path, monkeypatch):
    atomic = ui_runs.atomic_json
    errors = []

    def blocked_once(path, content):
        if path.name == "status.json" and content["estado"] == "concluida" and not errors:
            errors.append(path)
            raise PermissionError("leitor mantendo o arquivo aberto")
        return atomic(path, content)

    monkeypatch.setattr(ui_runs, "atomic_json", blocked_once)
    run_id = start_run(RunConfig(), tmp_path, spawn=lambda *args: None)
    run_worker(tmp_path, run_id, wait=lambda _: None)
    folder = run_path(tmp_path, run_id)
    assert len(errors) == 1
    assert status(folder)["estado"] == read_events(folder)[-1]["estado"] == "concluida"


def test_optional_events_keep_previous_result_and_limit_visible_records():
    frame, source = _synthetic_frame()
    old = run_loop(frame, source, ReplayConfig(2))
    events = []
    with_events = run_loop(frame, source, ReplayConfig(2), on_event=lambda *args: events.append(args))
    assert old == with_events
    for component, state, window, data in events:
        if component == "replay" and state == "concluida":
            assert all(1 <= p["Register"] <= window * 2 for p in data["pontos"])
            assert all(THROUGHPUT in p and PRB in p for p in data["pontos"])


def test_future_mcp_request_refused_and_partial_worker_error_audited(tmp_path):
    pytest.importorskip("mcp")
    frame, source = _synthetic_frame()
    events = []
    client = Client(target=2)
    result = run_loop(frame, source, ReplayConfig(2), agent_config=AgentConfig(selection="todas", max_calls=2),
                      mcp_reads=1, client=client, on_event=lambda *args: events.append(args),
                      before_window=lambda number, total: number == 1)
    assert len(client.chat) == 1
    assert client.chat[0]["janela"]["ultimo_register"] == 2
    assert result["agente"]["decisoes"][0]["fallback"]
    assert any(c == "mcp" and s == "falha" and "fora do contexto" in data["erro"].lower()
               for c, s, _, data in events)
    assert all(window in (None, 1) for _, _, window, _ in events)

    run_id = start_run(RunConfig(), tmp_path, spawn=lambda *args: None)
    folder = run_path(tmp_path, run_id)
    def fail_after_first(_):
        raise OSError("falha sintética de processamento")
    run_worker(tmp_path, run_id, wait=fail_after_first)
    assert status(folder)["estado"] == "falha"
    saved = read_events(folder)
    assert any(e["componente"] == "janela" and e["janela"] == 1 for e in saved)
    assert saved[-1]["estado"] == "falha"
    assert len(read_json(folder / "parcial.json")["janelas"]) == 1
