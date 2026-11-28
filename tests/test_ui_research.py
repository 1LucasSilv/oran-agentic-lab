"""Diário, leitura de registros e avaliação com dados locais sintéticos."""

import pytest

from oran_lab.experiment import atomic_json, read_json
from oran_lab.ollama import AgentConfig
from oran_lab.ui_experiments import Comparison, experiment_path, plan_comparison, run_worker, start_comparison
from oran_lab.ui_records import (
    Recording, compare_records, filter_rows, next_window, progress, recording_events, recordings,
    replay_prefix, result_rows, review_csv, reviewer_records, save_reviews,
)
from oran_lab.ui_runs import RunConfig, data_source


def test_diary_does_not_change_experimental_context(tmp_path):
    pytest.importorskip("mcp")
    from test_experiment import FixtureClient, FixtureRag

    calls = []

    def prepare(config, workspace):
        frame, source = data_source(config, workspace)
        resources = {"fonte": source, "gerador": {"digest": "fixture"}, "rag": {"arquivo_sha256": "fixture"}}
        return frame, source, resources, FixtureClient(config.agent, calls), FixtureRag()

    config = Comparison(RunConfig("E", agent=AgentConfig(num_ctx=8192, num_predict=512), mcp_reads=1,
                                  index="fixture.json"), ("demonstracao",), ("E",), (42,), target=5)
    plan = plan_comparison(config, tmp_path)
    records = []
    for instrument in (False, True):
        identifier = start_comparison(plan, tmp_path, confirmed=True, prepare_run=prepare, spawn=lambda *_: None)
        run_worker(tmp_path, identifier, prepare_run=prepare, instrument=instrument)
        records.append(Recording(experiment_path(tmp_path, identifier), "Configurável", identifier))
    assert len(calls) == 4
    assert [(s, p, opts) for s, p, opts, _ in calls[:2]] == [(s, p, opts) for s, p, opts, _ in calls[2:]]
    first, second = (result_rows(record)[0] for record in records)
    for key in ("acao_final", "proposta_acao", "fallback", "mcp_validas", "rag_apresentados", "origem_final"):
        assert first[key] == second[key]
    assert all(item["estado"] == "igual" for item in compare_records(*records))
    old, old_detail = recording_events(records[0])
    assert not old_detail and [event["componente"] for event in old] == ["janela", "sessao"]
    assert old[0]["data_utc"] is None
    events, detail = recording_events(records[1])
    assert detail and [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert all(event["data_utc"] and event["experimento"] == records[1].key for event in events)
    assert {"dataset", "replay", "detector", "selecao", "mcp", "rag", "inferencia", "proposta", "validacao",
            "execucao", "verificacao", "janela", "sessao"} <= {e["componente"] for e in events}
    replay = next(event for event in events if event["componente"] == "replay" and event["estado"] == "concluida")
    assert [item["Register"] for item in replay["dados"]["pontos"]] == [9, 10]
    limit = next_window(events, 0)
    assert not any(e["componente"] == "janela" for e in replay_prefix(events, limit - 1))
    assert replay_prefix(events, limit)[-1]["janela"] == 5
    totals, by_treatment, reserved, returned = progress(records[1], plan, events)
    assert totals["concluida"] == totals["processadas"] == by_treatment["E"]["processadas"] == 1
    assert reserved == returned == 2 and len(calls) == 4
    assert filter_rows([first, second], {"seed": {42}, "configuracao": {"E"}}) == [first, second]
    assert not filter_rows([first, second], {"modelo": {"ausente"}})


def test_partial_reviews_reuse_importer_preserve_history_and_require_revision(tmp_path):
    plan = plan_comparison(Comparison(RunConfig(), ("demonstracao",), ("A",), (42,), target=5), tmp_path)
    identifier = start_comparison(plan, tmp_path, confirmed=True, spawn=lambda *_: None)
    run_worker(tmp_path, identifier)
    record = recordings(tmp_path)[f"Configurável/{identifier}"]
    source = record.folder / "relatorios/avaliacao-cega.csv"
    before = source.read_bytes()
    [item] = read_json(record.folder / "relatorios/chave-avaliacao-local.json")
    data = review_csv([{"id": item, "fidelidade_kpm": 2, "comentario": "Parcial"}])
    assert save_reviews(tmp_path, record, "rev-1", data) == 1
    assert save_reviews(tmp_path, record, "rev-1", data) == 0
    assert save_reviews(tmp_path, record, "rev-1", review_csv([{"id": item, "correcao_tecnica": 1}])) == 1
    revised = review_csv([{"id": item, "fidelidade_kpm": 1}])
    with pytest.raises(ValueError, match="Autorize"):
        save_reviews(tmp_path, record, "rev-1", revised)
    assert save_reviews(tmp_path, record, "rev-1", revised, revise=True) == 1
    with pytest.raises(ValueError, match="inválida"):
        save_reviews(tmp_path, record, "rev-1", review_csv([{"id": item, "suporte_referencias": 1}]))
    assert reviewer_records(tmp_path, record, "rev-1")[item]["pontuacoes"] == {
        "fidelidade_kpm": 1, "correcao_tecnica": 1}
    assert source.read_bytes() == before and not (record.folder / "avaliacoes").exists()


def test_progress_reads_live_reservation_and_pending_sessions(tmp_path):
    plan = plan_comparison(Comparison(RunConfig("B", agent=AgentConfig()), ("demonstracao",), ("B",),
                                      (42,), repetitions=2, target=5), tmp_path)
    job = plan["execucoes"][0]
    event = {"sessao": job["id"], "componente": "inferencia", "janela": 5}
    record = Recording(tmp_path, "Configurável", "fixture")
    base = tmp_path / "execucoes" / job["id"]
    atomic_json(base / "chat/00001-inicio.json", {})
    totals, _, reserved, returned = progress(record, plan, [event])
    assert totals["pendente"] == totals["em_curso"] == 1
    assert totals["processadas"] == returned == 0 and reserved == 1
    atomic_json(base / "chat/00001-fim.json", {"erro": "fixture"})
    atomic_json(base / "eventos/janela-0005.json", {})
    atomic_json(base / "resultado.json", {"estado": "interrompida"})
    totals, _, reserved, returned = progress(record, plan, [event])
    assert totals["processadas"] == reserved == returned == totals["interrompida"] == 1
