"""Integração com o SDK real e respostas de modelo injetadas."""

import asyncio
import json
import os

import pytest

pytest.importorskip("mcp")
from mcp import Client

from oran_lab.agent import AgentConfig
from oran_lab.detector import DetectorConfig, detect
from oran_lab.loop import _synthetic_frame, run_loop
from oran_lab.mcp_client import MCPWindow, call, demo, discover, parse_read
from oran_lab.mcp_server import create_server
from oran_lab.replay import ReplayConfig
from oran_lab.simulator import Simulator

REGISTER = {"acao": "registrar_alerta", "parametros": {"evento_id": "alerta-5"}, "justificativa": "Teste"}
QUERY = {"ferramenta": "consultar_historico", "parametros": {"limite": 4}}


class Model:
    def __init__(self, *outputs):
        self.outputs = iter(outputs)
        self.payloads = []

    def metadata(self):
        return {}

    def residency(self):
        return {}

    def request(self, path, payload):
        self.payloads.append(payload)
        return 200, json.dumps({"done": True, "message": {
            "role": "assistant", "content": json.dumps(next(self.outputs)),
        }})


def test_real_memory_protocol():
    async def check():
        frame, _ = _synthetic_frame()
        detections = list(detect(frame, ReplayConfig(2), DetectorConfig()))
        sim = Simulator(frame, detections, 2)
        server = create_server(sim, frame, {d["janela"]["id"]: d for d in detections}, 5, max_reads=6)
        async with Client(server) as client:
            assert len(await discover(client)) == 5
            with pytest.raises(ValueError):
                await call(client, "consultar_janela", {"janela_id": 6})
            with pytest.raises(ValueError):
                await call(client, "consultar_historico", {"limite": True})
            with pytest.raises(ValueError):
                await call(client, "consultar_historico", {"limite": 33})
            with pytest.raises(ValueError):
                await call(client, "consultar_estado", {"janela_id": 6})
            assert "registrar_alerta" in (await call(client, "listar_acoes_permitidas", {}))["acoes"]
            assert (await call(client, "consultar_janela", {"janela_id": 4}))["janela"]["id"] == 4
            records = (await call(client, "consultar_historico", {"limite": 4}))["registros"]
            assert [row["Register"] for row in records] == [7, 8, 9, 10]
            assert (await call(client, "solicitar_acao", REGISTER))["execucao"]["estado"] == "executada"
            assert (await call(client, "consultar_estado", {}))["evento_atual"]["evento_id"] == "alerta-5"
            with pytest.raises(ValueError, match="Orçamento"):
                await call(client, "consultar_estado", {})
            assert (await call(client, "solicitar_acao", REGISTER))["validacao"]["estado"] == "recusada"
            assert len(sim.state()["alertas"]) == 1
    asyncio.run(check())


def test_model_selects_and_receives_causal_mcp_history():
    frame, source = _synthetic_frame()
    settings = dict(agent_config=AgentConfig(max_calls=2), mcp_reads=2)
    model = Model(QUERY, REGISTER)
    original = run_loop(frame, source, ReplayConfig(2), client=model, **settings)
    frame.loc[10:, "DRB.UEThpUl"] = 0
    second = Model(QUERY, REGISTER)
    run_loop(frame, source, ReplayConfig(2), client=second, **settings)
    assert model.payloads == second.payloads
    decision = original["agente"]["decisoes"][4]
    assert decision["origem_execucao"] == "ollama"
    assert [t["nome"] for t in decision["mcp"]["ferramentas"]] == [None, "consultar_historico", "solicitar_acao"]
    assert decision["contexto_final"]["consultas_mcp"][0]["resultado"]["registros"][-1]["Register"] == 10


@pytest.mark.parametrize("query", [
    {"ferramenta": "solicitar_acao", "parametros": {}},
    {"ferramenta": "consultar_historico", "parametros": {"limite": 33}},
    {"ferramenta": "consultar_janela", "parametros": {"janela_id": True}},
])
def test_invalid_model_selection(query):
    with pytest.raises(ValueError):
        parse_read(json.dumps(query))


def test_future_selection_uses_python_fallback_through_mcp():
    frame, source = _synthetic_frame()
    model = Model({"ferramenta": "consultar_janela", "parametros": {"janela_id": 6}})
    result = run_loop(frame, source, ReplayConfig(2), client=model,
                      agent_config=AgentConfig(max_calls=2, max_failures=1), mcp_reads=2)
    decision = result["agente"]["decisoes"][4]
    assert decision["origem_execucao"] == "fallback_python"
    assert "erro" in decision["mcp"]["ferramentas"][1]
    assert decision["mcp"]["ferramentas"][-1]["resultado"]["execucao"]["estado"] == "executada"


def test_mcp_timeout_has_no_local_mutation(monkeypatch):
    async def timeout(*args):
        raise TimeoutError("tempo esgotado")

    monkeypatch.setattr("oran_lab.mcp_client.call", timeout)
    frame, source = _synthetic_frame()
    result = run_loop(frame, source, ReplayConfig(2), client=Model(REGISTER),
                      agent_config=AgentConfig(max_calls=1), mcp_reads=0)
    decision = result["agente"]["decisoes"][4]
    assert decision["fallback"]["acao"] == "nenhuma_acao"
    assert decision["origem_execucao"] is None
    assert result["simulador"]["estado_inicial"] == result["simulador"]["estado_final"]


def test_contextual_action_denied_in_both_entry_points():
    frame, _ = _synthetic_frame()
    detections = list(detect(frame, ReplayConfig(2), DetectorConfig()))
    sim = Simulator(frame, detections, 2)
    sim.apply(REGISTER, window_id=5, origin="politica_deterministica")
    proposal = {"acao": "priorizar_evento", "parametros": {"evento_id": "alerta-5", "prioridade": "alta"},
                "justificativa": "Alvo de outra janela"}
    denied = sim.apply(proposal, origin="ollama", window_id=7)
    assert denied["validacao"]["estado"] == "recusada"
    window = MCPWindow(sim, frame, {d["janela"]["id"]: d for d in detections}, 7, 2, 5)
    denied = window.apply(proposal, "ollama")
    assert denied["validacao"]["estado"] == "recusada"
    assert denied["estado_anterior"] == denied["estado_posterior"]


@pytest.mark.skipif(os.getenv("ORAN_TEST_MCP_STDIO") != "1", reason="requer subprocesso MCP stdio")
def test_real_stdio_protocol():
    result = asyncio.run(demo())
    assert len(result["ferramentas"]) == 5
    assert result["acao_valida"]["execucao"]["estado"] == "executada"
    assert result["acao_invalida"]["validacao"]["estado"] == "recusada"
    assert result["estado"]["evento_atual"]["evento_id"] == "alerta-5"


def test_invalid_reply_after_commit_preserves_authoritative_audit(monkeypatch):
    real_call = call

    async def invalid_ack(client, name, params):
        result = await real_call(client, name, params)
        return {"id": "incorreto"} if name == "solicitar_acao" else result

    monkeypatch.setattr("oran_lab.mcp_client.call", invalid_ack)
    frame, source = _synthetic_frame()
    result = run_loop(frame, source, ReplayConfig(2), client=Model(REGISTER),
                      agent_config=AgentConfig(max_calls=1), mcp_reads=0)
    decision = result["agente"]["decisoes"][4]
    assert decision["mcp"]["erro_acao"]
    assert decision["fallback"] is None
    assert decision["origem_execucao"] == "ollama"
    assert len([e for e in result["simulador"]["historico"] if e["janela_id"] == 5]) == 1
