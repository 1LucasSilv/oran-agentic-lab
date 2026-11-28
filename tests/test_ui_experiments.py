from dataclasses import replace

import pandas as pd
import pytest

from oran_lab.agent import EXPERIMENT_PROMPT
from oran_lab.experiment import read_json
from oran_lab.ollama import AgentConfig
from oran_lab.ui_experiments import (Comparison, experiment_path, plan_comparison, request_interruption,
                                     run_worker, start_comparison)
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


def test_two_models_same_architecture_pair_two_repetitions(tmp_path):
    pytest.importorskip("mcp")
    from test_experiment import FixtureClient, FixtureRag

    calls = []
    models = ("primeiro:1", "segundo:1")
    identities = dict(zip(models, ("a" * 64, "b" * 64), strict=True))

    def prepare(config, workspace):
        frame, source = data_source(config, workspace)
        client = FixtureClient(config.agent, calls)
        generator = {"tag": config.agent.model, "digest": identities[config.agent.model],
                     "arquitetura_modelo": "fixture", "parametros_modelo": 123}
        return frame, source, {"fonte": source, "gerador": generator, "rag": {"arquivo_sha256": "fixture"}}, client, FixtureRag()

    template = RunConfig("E", agent=AgentConfig(num_ctx=8192, num_predict=512), mcp_reads=1, index="indice.json")
    config = Comparison(template, ("demonstracao",), ("E",), (42,), 2, 8, target=5,
                        model_treatments=tuple(("E", model) for model in models))
    plan = plan_comparison(config, tmp_path)
    assert plan["n_sessoes"] == plan["n_oportunidades"] == 4
    assert plan["max_chat"] == 8 and not calls
    identifier = start_comparison(plan, tmp_path, confirmed=True, prepare_run=prepare, spawn=lambda *_: None)
    run_worker(tmp_path, identifier, prepare_run=prepare)
    directory = experiment_path(tmp_path, identifier)
    assert status(directory)["estado"] == "concluida"
    manifest = read_json(directory / "manifesto.json")
    assert {entry["gerador"]["digest"] for entry in manifest["tratamentos"].values()} == set(identities.values())
    assert all(entry["arquitetura"] == "E" for entry in manifest["tratamentos"].values())
    assert len(calls) == 8 and {client.options.model for _, _, _, client in calls} == set(models)
    assert len({id(client) for _, _, _, client in calls}) == 4
    finals = [(payload, opts) for system, payload, opts, _ in calls if system == EXPERIMENT_PROMPT]
    assert all(opts == finals[0][1] and payload == finals[0][0] for payload, opts in finals)
    output = directory / "relatorios"
    decisions = pd.read_csv(output / "decisoes.csv")
    assert set(decisions["repeticao"]) == {1, 2} and set(decisions["modelo"]) == set(models)
    assert set(decisions["mcp_validas"]) == {1} and set(decisions["rag_apresentados"]) == {1}
    pairs = pd.read_csv(output / "pareadas_por_caso.csv")
    assert set(pairs["base"]) == {"E-01"} and set(pairs["tratamento"]) == {"E-02"}
    assert set(pairs["n_pares_janela_semente_repeticao"]) == {2}
    assert {"descritivas.csv", "contagens.json", "avaliacao-cega.csv", "custos_computacionais.png"} <= {
        path.name for path in output.iterdir()
    }


def test_interruption_finishes_current_window_and_preserves_partial_report(tmp_path):
    from test_experiment import FixtureClient

    calls = []
    config = Comparison(RunConfig("B", agent=AgentConfig(num_ctx=8192, num_predict=512)),
                        ("demonstracao",), ("B",), (42,), 2, 16, mode="ciclo_completo")

    class StoppingClient(FixtureClient):
        def request(self, path, payload):
            request_interruption(tmp_path, identifier)
            request_interruption(tmp_path, identifier)
            return super().request(path, payload)

    def prepare(options, workspace):
        frame, source = data_source(options, workspace)
        client = StoppingClient(options.agent, calls)
        return frame, source, {"fonte": source, "gerador": {"digest": "fixture"}}, client, None

    plan = plan_comparison(config, tmp_path)
    identifier = start_comparison(plan, tmp_path, confirmed=True, prepare_run=prepare, spawn=lambda *_: None)
    run_worker(tmp_path, identifier, prepare_run=prepare)
    directory = experiment_path(tmp_path, identifier)
    snapshot = status(directory)
    assert snapshot["estado"] == "interrompida" and snapshot["interrompidas"] == 1 and snapshot["chat"] == 1
    [result] = directory.glob("execucoes/*/resultado.json")
    assert read_json(result)["janelas_concluidas"] == 1
    [window] = directory.glob("execucoes/*/eventos/janela-*.json")
    assert read_json(window)["janela"] == 1
    decisions = pd.read_csv(directory / "relatorios/decisoes.csv")
    assert len(decisions) == 16 and decisions["avaliada"].sum() == 1
    assert set(decisions["estado_execucao"]) == {"interrompida", "pendente"}
    with pytest.raises(ValueError, match="encerrou"):
        request_interruption(tmp_path, identifier)
    run_worker(tmp_path, identifier, prepare_run=prepare)
    assert len(calls) == 1 and status(directory) == snapshot


def test_interruption_before_first_session_uses_zero_chat(tmp_path):
    plan = plan_comparison(Comparison(RunConfig(), ("demonstracao",), ("A",), (42,), target=5), tmp_path)
    identifier = start_comparison(plan, tmp_path, confirmed=True, spawn=lambda *_: None)
    request_interruption(tmp_path, identifier)
    run_worker(tmp_path, identifier)
    directory = experiment_path(tmp_path, identifier)
    assert status(directory)["estado"] == "interrompida" and status(directory)["chat"] == 0
    assert not list(directory.glob("execucoes/*/resultado.json"))
