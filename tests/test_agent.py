"""Respostas sintéticas injetadas. O único teste real exige opt-in explícito."""

import json
import os
from copy import deepcopy

import pytest

from oran_lab.agent import AgentConfig, SCHEMA, parse_proposal
from oran_lab.loop import _synthetic_frame, run_loop
from oran_lab.replay import ReplayConfig
from oran_lab.simulator import EXPAND, INTENSIFY, NO_ACTION, PRIORITIZE, REGISTER_ALERT


def proposal(action=NO_ACTION, **params):
    return {"acao": action, "parametros": params, "justificativa": "Teste sintético"}


def reply(obj):
    content = obj if isinstance(obj, str) else json.dumps(obj)
    return 200, json.dumps({"done": True, "model": "mock", "eval_count": 12, "prompt_eval_count": 80,
                            "message": {"role": "assistant", "content": content}})


class MockClient:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.payloads = []

    def metadata(self):
        return {"teste": True}

    def residency(self):
        return {}

    def request(self, path, payload):
        assert path == "/api/chat"
        self.payloads.append(deepcopy(payload))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def run(client, frame=None, **options):
    original, source = _synthetic_frame()
    return run_loop(original if frame is None else frame, source, ReplayConfig(2),
                    agent_config=AgentConfig(**options), client=client)


@pytest.mark.parametrize("action,params", [
    (NO_ACTION, {}), (REGISTER_ALERT, {"evento_id": "alerta-5"}),
    (PRIORITIZE, {"evento_id": "alerta-5", "prioridade": "alta"}),
    (EXPAND, {"evento_id": "alerta-5", "tamanho_registros": 5}),
    (INTENSIFY, {"evento_id": "alerta-5", "avanco_registros": 1}),
])
def test_all_actions_through_model_and_simulator(action, params):
    client = MockClient(reply(proposal(REGISTER_ALERT, evento_id="alerta-5")), reply(proposal(action, **params)))
    result = run(client)
    first, second = result["agente"]["decisoes"][4:6]
    assert first["origem_execucao"] == "ollama"
    assert second["metricas_ollama"]["eval_count"] == 12
    assert second["proposta_modelo"] == proposal(action, **params)
    if action == REGISTER_ALERT:
        assert second["fallback"]["acao"] == NO_ACTION
        assert second["origem_decisao_final"] == "fallback_python"
    else:
        assert second["origem_decisao_final"] == "ollama"
    assert client.payloads[0]["format"] == SCHEMA and client.payloads[0]["stream"] is False
    assert client.payloads[0]["options"]["temperature"] == 0
    assert all(e["origem"] != "cenario_controlado" for e in result["simulador"]["historico"])


@pytest.mark.parametrize("raw", [
    "", "{}", "{", "[]", json.dumps(proposal("shell")), json.dumps(proposal() | {"janela_id": 1}),
    json.dumps(proposal() | {"justificativa": " "}), json.dumps(proposal() | {"parametros": []}),
    json.dumps(proposal(EXPAND, tamanho_registros=True, evento_id="alerta-5")),
    '{"acao":"nenhuma_acao","acao":"nenhuma_acao","parametros":{},"justificativa":"x"}',
    '{"acao":"nenhuma_acao","parametros":{"x":NaN},"justificativa":"x"}',
    '{"acao":"nenhuma_acao","parametros":{},"justificativa":1e999}',
])
def test_strict_response_contract(raw):
    with pytest.raises(ValueError):
        parse_proposal(raw)


@pytest.mark.parametrize("response", [
    TimeoutError("tempo"), ConnectionRefusedError("indisponível"),
    (404, '{"error":"model not found"}'), (500, "erro"), (200, ""), (200, '[]'),
    (200, '{"done":false}'), (200, '{"done":true,"done_reason":"length"}'),
    reply("{"), reply(proposal("executar_shell")), reply(proposal(PRIORITIZE, evento_id="inventado", prioridade="alta")),
])
def test_failure_audit_and_python_fallback(response):
    client = MockClient(response)
    result = run(client, max_failures=1)
    audit = result["agente"]
    first, skipped = audit["decisoes"][4:6]
    assert audit["chamadas"] == audit["falhas"] == 1 and audit["fallbacks"] == 2
    assert first["erro"] and first["fallback"]["acao"] == REGISTER_ALERT
    assert first["origem_execucao"] == "fallback_python"
    assert skipped["dispensa"] == "circuito_aberto" and skipped["contexto"] is None
    if first["historico_modelo"]:
        entry = result["simulador"]["historico"][first["historico_modelo"] - 1]
        assert entry["estado_anterior"] == entry["estado_posterior"]
        assert entry["validacao"]["estado"] == "recusada"
    assert result["simulador"]["estado_final"]["alertas"]["alerta-5"]["janela_id"] == 5


def test_operational_limit_and_causal_context():
    def execute(frame):
        client = MockClient(reply(proposal(REGISTER_ALERT, evento_id="alerta-5")),
                            reply(proposal(EXPAND, evento_id="alerta-5", tamanho_registros=999)))
        result = run(client, frame)
        decision = result["agente"]["decisoes"][5]
        assert "máximo" in decision["erro"]
        assert decision["origem_execucao"] is None
        assert decision["contexto"]["evento_atual"]["evento_id"] == "alerta-5"
        return client.payloads

    frame, _ = _synthetic_frame()
    expected = execute(frame)
    frame.loc[12:, "DRB.UEThpUl"] = 98765
    assert execute(frame)[:2] == expected


def test_budget_and_selection_are_not_model_successes():
    result = run(MockClient(reply(proposal())), max_calls=1, selection="todas")
    audit = result["agente"]
    assert audit["chamadas"] == 1 and audit["falhas"] == audit["fallbacks"] == 0
    assert all(d["dispensa"] == "orcamento_esgotado" for d in audit["decisoes"][1:])
    assert audit["decisoes"][4]["origem_execucao"] == "politica_deterministica"


@pytest.mark.parametrize("url", ["http://example.org", "https://127.0.0.1", "http://localhost@evil.org"])
def test_local_api_only(url):
    with pytest.raises(ValueError):
        AgentConfig(url=url)


@pytest.mark.skipif(os.getenv("ORAN_TEST_OLLAMA") != "1", reason="requer serviço Ollama real")
def test_local_ollama_integration():
    result = run(None, max_calls=1)
    decision = result["agente"]["decisoes"][4]
    assert decision["status_http"] == 200 and decision["proposta_modelo"], decision["erro"]
    attempt = result["simulador"]["historico"][decision["historico_modelo"] - 1]
    assert attempt["origem"] == "ollama"
    if attempt["validacao"]["estado"] == "recusada":
        assert attempt["estado_anterior"] == attempt["estado_posterior"]
        assert decision["origem_decisao_final"] == "fallback_python"
    else:
        assert decision["origem_decisao_final"] == "ollama"
