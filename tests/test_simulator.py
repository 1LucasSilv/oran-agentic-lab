"""Cenários sintéticos locais com expectativas de detecção e ação pré-definidas."""

import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

import pandas as pd
import pytest
from openpyxl import Workbook

from oran_lab.detector import PRB, THROUGHPUT, DetectorConfig, detect
from oran_lab.loop import main, propose
from oran_lab.replay import ReplayConfig
from oran_lab.simulator import EXPAND, INTENSIFY, NO_ACTION, PRIORITIZE, REGISTER_ALERT, Limits, Simulator


EVENT = "alerta-5"


@pytest.fixture
def synthetic_history():
    levels = [100] * 6 + [50] * 6 + [100] * 2 + [50] * 4
    frame = pd.DataFrame({
        "Register": range(1, len(levels) + 1), "UE.Id": 1, THROUGHPUT: levels, PRB: 1000,
    })
    windows = list(detect(frame, ReplayConfig(size=2), DetectorConfig()))
    return frame, windows


def proposal(action, **params):
    return {"acao": action, "parametros": params, "justificativa": "Teste controlado"}


def apply(sim, action, window_id=None, **params):
    return sim.apply(proposal(action, **params), origin="teste_sintetico", window_id=window_id)


def register(sim):
    return apply(sim, REGISTER_ALERT, window_id=5, evento_id=EVENT)


def assert_refused(entry, reason):
    assert entry["validacao"]["estado"] == "recusada"
    assert reason in entry["validacao"]["justificativa"]
    assert entry["execucao"]["estado"] == "nao_executada"
    assert entry["verificacao"]["estado"] == "nao_aplicavel"
    assert entry["estado_anterior"] == entry["estado_posterior"]
    assert entry["alteracoes"] == {}


@pytest.fixture
def simulator(synthetic_history):
    frame, windows = synthetic_history
    return Simulator(frame, windows, 2)


def test_detector_policy_registers_only_opening_window(synthetic_history, simulator):
    _, windows = synthetic_history
    assert [d["janela"]["id"] for d in windows if d["novo_alerta"]] == [5, 9]
    assert [propose(windows[i])["acao"] for i in (0, 4, 5, 6)] == [
        NO_ACTION, REGISTER_ALERT, NO_ACTION, NO_ACTION,
    ]
    entry = simulator.apply(propose(windows[4]), window_id=5, origin="politica_deterministica")
    assert entry["validacao"]["estado"] == "aceita"
    assert entry["execucao"]["estado"] == "executada"
    assert entry["verificacao"]["estado"] == "aprovada"
    assert entry["evento_id"] == EVENT
    assert entry["janela_id"] == 5
    assert entry["origem"] == "politica_deterministica"
    assert entry["estado_anterior"]["alertas"] == {}
    alert = entry["estado_posterior"]["alertas"][EVENT]
    assert alert["janela_id"] == 5
    assert alert["regra"] == windows[4]["regra"]
    assert set(entry["alteracoes"]) == {"alertas", "eventos"}


def test_duplicate_alert_is_refused_even_when_submitted_concurrently(simulator):
    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted, refused = sorted(pool.map(lambda _: register(simulator), range(2)), key=lambda x: x["id"])
    assert accepted["execucao"]["estado"] == "executada"
    assert_refused(refused, "já registrado")
    assert list(simulator.state()["alertas"]) == [EVENT]
    assert len(simulator.history()) == 2


def test_priority_updates_existing_event_and_is_idempotent(simulator):
    register(simulator)
    entry = apply(simulator, PRIORITIZE, evento_id=EVENT, prioridade="alta")
    change = entry["alteracoes"]["eventos"]
    assert change["antes"][EVENT]["prioridade"] == "normal"
    assert change["depois"][EVENT]["prioridade"] == "alta"
    repeated = apply(simulator, PRIORITIZE, evento_id=EVENT, prioridade="alta")
    assert repeated["validacao"]["estado"] == "aceita"
    assert repeated["execucao"]["estado"] == "nao_executada"
    assert repeated["verificacao"]["estado"] == "aprovada"
    assert repeated["estado_anterior"] == repeated["estado_posterior"]


def test_expansion_queries_metrics_of_only_new_historical_registers(synthetic_history, simulator):
    frame, _ = synthetic_history
    original = frame.copy(deep=True)
    register(simulator)
    first = apply(simulator, EXPAND, evento_id=EVENT, tamanho_registros=5)
    analysis = first["estado_posterior"]["eventos"][EVENT]["analise"]
    assert first["verificacao"]["estado"] == "aprovada"
    assert analysis["tamanho_registros"] == 5
    assert analysis["primeiro_register"] == 6
    query, = analysis["consultas"]
    assert query["registros"] == [6, 7, 8]
    assert query["quantidade"] == 3
    assert query["metricas"][THROUGHPUT]["mediana"] == 50
    assert first["estado_posterior"]["analise"]["registros_adicionais_consultados"] == 3
    repeated = apply(simulator, EXPAND, evento_id=EVENT, tamanho_registros=5)
    assert repeated["execucao"]["estado"] == "nao_executada"
    second = apply(simulator, EXPAND, evento_id=EVENT, tamanho_registros=7)
    second_analysis = second["estado_posterior"]["eventos"][EVENT]["analise"]
    assert second_analysis["consultas"][1]["registros"] == [4, 5]
    assert second["estado_posterior"]["analise"]["registros_adicionais_consultados"] == 5
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("size, expected", [(8, "máximo"), (6, "orçamento"), (True, "inteiro"), (1, "inteiro")])
def test_expansion_limits_are_enforced(synthetic_history, size, expected):
    frame, windows = synthetic_history
    sim = Simulator(frame, windows, 2, Limits(max_history_size=7, history_budget=3))
    register(sim)
    assert_refused(apply(sim, EXPAND, evento_id=EVENT, tamanho_registros=size), expected)
    assert sim.state()["analise"]["registros_adicionais_consultados"] == 0


def test_expansion_budget_is_shared_across_events(synthetic_history):
    frame, windows = synthetic_history
    sim = Simulator(frame, windows, 2, Limits(history_budget=3))
    register(sim)
    apply(sim, REGISTER_ALERT, window_id=9, evento_id="alerta-9")
    assert apply(sim, EXPAND, evento_id=EVENT, tamanho_registros=4)["execucao"]["estado"] == "executada"
    assert_refused(apply(sim, EXPAND, evento_id="alerta-9", tamanho_registros=4), "orçamento")


def test_expansion_preserves_segment_and_refuses_to_cross_gap(synthetic_history):
    frame, _ = synthetic_history
    frame["Register"] += 10
    prefix = frame.iloc[:2].assign(Register=[1, 2])
    frame = pd.concat([prefix, frame], ignore_index=True)
    windows = list(detect(frame, ReplayConfig(size=2), DetectorConfig()))
    sim = Simulator(frame, windows, 2)
    entry = apply(sim, REGISTER_ALERT, window_id=6, evento_id="alerta-6")
    assert entry["execucao"]["estado"] == "executada"
    assert_refused(apply(sim, EXPAND, evento_id="alerta-6", tamanho_registros=11), "contíguo")


def test_intensification_changes_only_future_inspection_config(synthetic_history):
    frame, windows = synthetic_history
    sim = Simulator(frame, windows, 4, Limits(min_inspection_stride=2))
    register(sim)
    entry = apply(sim, INTENSIFY, evento_id=EVENT, avanco_registros=2)
    assert entry["alteracoes"] == {
        "inspecao": {"antes": {"avanco_registros": 4}, "depois": {"avanco_registros": 2}},
    }
    assert entry["verificacao"]["estado"] == "aprovada"
    assert_refused(apply(sim, INTENSIFY, evento_id=EVENT, avanco_registros=1), "mínimo")
    assert_refused(apply(sim, INTENSIFY, evento_id=EVENT, avanco_registros=3), "avanço atual")
    assert apply(sim, INTENSIFY, evento_id=EVENT, avanco_registros=2)["execucao"]["estado"] == "nao_executada"


def test_no_action_is_audited_even_for_insufficient_evidence(simulator):
    entry = apply(simulator, NO_ACTION, window_id=1)
    assert entry["validacao"]["estado"] == "aceita"
    assert entry["execucao"]["estado"] == "nao_executada"
    assert entry["verificacao"]["estado"] == "aprovada"
    assert entry["estado_anterior"] == entry["estado_posterior"] == simulator.state()
    assert entry["evento_id"] is None
    assert entry["alteracoes"] == {}
    assert simulator.history() == [entry]


@pytest.mark.parametrize("action, params, window, reason", [
    ("acao_inexistente", {}, None, "desconhecida"),
    (NO_ACTION, {"prioridade": "alta"}, None, "Parâmetros"),
    (NO_ACTION, {}, 999, "janela inexistente"),
    (PRIORITIZE, {"evento_id": "ausente", "prioridade": "alta"}, None, "Evento inexistente"),
    (REGISTER_ALERT, {"evento_id": EVENT}, 1, "novo episódio"),
    (REGISTER_ALERT, {"evento_id": EVENT}, 6, "novo episódio"),
    (REGISTER_ALERT, {"evento_id": "divergente"}, 5, "correspondente"),
    (REGISTER_ALERT, {"evento_id": None}, 5, "evento inválido"),
])
def test_invalid_proposals_are_safe(simulator, action, params, window, reason):
    assert_refused(apply(simulator, action, window_id=window, **params), reason)


def test_priority_and_proposal_shape_validation(simulator):
    register(simulator)
    assert_refused(apply(simulator, PRIORITIZE, evento_id=EVENT, prioridade="urgente"), "Prioridade")
    missing_justification = {"acao": NO_ACTION, "parametros": {}, "justificativa": " "}
    assert_refused(simulator.apply(missing_justification, origin="teste"), "Justificativa")
    bad = proposal(EXPAND, evento_id=EVENT, tamanho_registros=float("nan"))
    result = simulator.apply(bad, origin="teste")
    assert_refused(result, "serializável")
    assert json.dumps(simulator.history(), allow_nan=False)


def test_suspicious_label_requires_supported_evidence(synthetic_history):
    frame, windows = synthetic_history
    windows[4]["metricas"][THROUGHPUT]["mediana"] = None
    sim = Simulator(frame, windows, 2)
    assert_refused(register(sim), "insuficientes")


@pytest.mark.parametrize("unexpected_result", ["exception", "mismatch"])
def test_execution_failure_rolls_back(simulator, monkeypatch, unexpected_result):
    def broken(state, action, params, detection):
        state["inspecao"]["avanco_registros"] = 1
        if unexpected_result == "exception":
            raise OSError("falha de teste")

    monkeypatch.setattr(simulator, "_execute", broken)
    entry = register(simulator)
    assert entry["validacao"]["estado"] == "aceita"
    assert entry["execucao"]["estado"] == "falha"
    assert entry["verificacao"]["estado"] == "reprovada"
    assert entry["estado_anterior"] == entry["estado_posterior"] == simulator.state()
    assert entry["alteracoes"] == {}


def test_integrated_synthetic_demo_is_reproducible(tmp_path):
    outputs = [tmp_path / "primeira", tmp_path / "segunda"]
    for output in outputs:
        main(["--sintetico", "--saida", str(output)])
    for name in ("resultados.json", "relatorio.md"):
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes()
    result = json.loads((outputs[0] / "resultados.json").read_text(encoding="utf-8"))
    assert result["fonte"]["tipo"] == "sintetico"
    state = result["simulador"]
    assert state["estado_inicial"]["alertas"] == {}
    assert state["estado_final"]["eventos"][EVENT]["prioridade"] == "alta"
    assert [entry["id"] for entry in state["historico"] if entry["execucao"]["estado"] == "executada"] == [5, 10, 11, 13]
    assert [entry["id"] for entry in state["historico"] if entry["validacao"]["estado"] == "recusada"] == [9, 12]


def test_integrated_excel_preserves_source_and_detection(synthetic_history, tmp_path):
    frame, expected = synthetic_history
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "KPM Metrics"
    sheet.append(list(frame.columns))
    for row in frame.itertuples(index=False, name=None):
        sheet.append(row)
    path = tmp_path / "kpm_fixture_sintetica.xlsx"
    workbook.save(path)
    content = path.read_bytes()
    output = tmp_path / "excel"
    main([str(path), "--tamanho", "2", "--saida", str(output)])
    result = json.loads((output / "resultados.json").read_text(encoding="utf-8"))
    assert result["deteccoes"] == json.loads(json.dumps(expected))
    assert set(result["simulador"]["estado_final"]["alertas"]) == {EVENT, "alerta-9"}
    assert result["fonte"]["sha256"] == sha256(content).hexdigest()
    assert result["fonte"]["tipo"] == "outro_excel"
    assert path.read_bytes() == content
