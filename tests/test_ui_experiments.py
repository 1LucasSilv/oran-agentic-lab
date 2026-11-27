from dataclasses import replace

import pytest

from oran_lab.agent import EXPERIMENT_PROMPT
from oran_lab.experiment import read_json
from oran_lab.ollama import AgentConfig
from oran_lab.ui_experiments import Comparison, experiment_path, plan_comparison, run_worker, start_comparison
from oran_lab.ui_resources import operation
from oran_lab.ui_runs import RunConfig, data_source, start_run, status


def test_comparison_common_variables_and_budget(tmp_path):
    template = RunConfig("E", agent=AgentConfig(num_ctx=8192, num_predict=512), mcp_reads=1, index="indice.json")
    config = Comparison(template, ("demonstracao",), tuple("ABCDE"), (42, 43), 2, 23, target=5)
    plan = plan_comparison(config, tmp_path)
    assert plan == plan_comparison(config, tmp_path)
    assert plan["n_sessoes"] == plan["n_oportunidades"] == 20
    assert plan["max_chat"] == 24
    assert plan["fontes"]["demonstracao"]["janelas"] == [5]
    assert all(job["janelas"] == [5] and job["tratamento"]["replay"] == plan["configuracao"]["template"]["replay"]
               for job in plan["execucoes"])
    options = [job["tratamento"]["agent"] for job in plan["execucoes"] if job["configuracao"] != "A"]
    assert {item["model"] for item in options} == {template.agent.model}
    assert {item["num_ctx"] for item in options} == {8192}
    with pytest.raises(ValueError, match="orçamento"):
        start_comparison(plan, tmp_path, confirmed=True)
    with pytest.raises(ValueError, match="Confirme"):
        start_comparison(plan, tmp_path)
    full = plan_comparison(replace(config, mode="ciclo_completo"), tmp_path)
    assert full["n_oportunidades"] == 20 * 8 and full["max_chat"] == 24 * 8


def test_worker_shared_slot_and_immutable_results(tmp_path):
    config = Comparison(RunConfig(), ("demonstracao",), ("A",), (42, 43), max_chat=0, target=5)
    plan = plan_comparison(config, tmp_path)
    with operation(tmp_path):
        with pytest.raises(ValueError, match="ativa"):
            start_comparison(plan, tmp_path, confirmed=True, spawn=lambda *_: None)
    identifier = start_comparison(plan, tmp_path, confirmed=True, spawn=lambda *_: None)
    with pytest.raises(ValueError, match="ativa"):
        start_run(RunConfig(), tmp_path, spawn=lambda *_: None)
    run_worker(tmp_path, identifier)
    directory = experiment_path(tmp_path, identifier)
    final = status(directory)
    assert final["estado"] == "concluida" and final["concluidas"] == 2 and final["chat"] == 0
    preparations = [read_json(path) for path in directory.glob("execucoes/*/eventos/preparacao.json")]
    assert preparations[0] == preparations[1]
    assert not list(directory.glob("execucoes/*/eventos/janela-0006.json"))
    assert (directory / "relatorios").is_dir()
    run_worker(tmp_path, identifier)
    assert status(directory) == final


def test_controlled_fixture_preserves_evidence_and_bounds_chat(tmp_path):
    pytest.importorskip("mcp")
    from test_experiment import FixtureClient, FixtureRag

    calls = []

    def prepare(config, workspace):
        frame, source = data_source(config, workspace)
        client = FixtureClient(config.agent, calls) if config.agent else None
        rag = FixtureRag() if config.index else None
        resources = {"fonte": source}
        if client:
            resources["gerador"] = client.metadata()
        if rag:
            resources["rag"] = {"arquivo_sha256": "fixture"}
        return frame, source, resources, client, rag

    template = RunConfig("E", agent=AgentConfig(num_ctx=8192, num_predict=512), mcp_reads=1, index="indice.json")
    plan = plan_comparison(Comparison(template, ("demonstracao",), tuple("ABCDE"), (42,), max_chat=6, target=5), tmp_path)
    assert not calls
    identifier = start_comparison(plan, tmp_path, confirmed=True, prepare_run=prepare, spawn=lambda *_: None)
    run_worker(tmp_path, identifier, prepare_run=prepare)
    directory = experiment_path(tmp_path, identifier)
    final = status(directory)
    assert final["estado"] == "concluida" and final["concluidas"] == 5 and final["falhas"] == 0
    assert final["chat"] == len(calls) == 6
    final_calls = [(payload, options, client) for system, payload, options, client in calls if system == EXPERIMENT_PROMPT]
    assert len(final_calls) == 4 and len({id(client) for _, _, client in final_calls}) == 4
    assert all(options == final_calls[0][1] for _, options, _ in final_calls)
    assert all(payload["janela"] == final_calls[0][0]["janela"] for payload, _, _ in final_calls)
    assert all(payload["detector"] == final_calls[0][0]["detector"] for payload, _, _ in final_calls)
    assert sum(bool(payload["referencias_3gpp"]) for payload, _, _ in final_calls) == 2
    assert len(list(directory.glob("execucoes/*/chat/*-inicio.json"))) == 6
