"""Reprodução da Etapa 7 sem modelos, corpus ou Excel real."""

import csv
import json
from dataclasses import replace

import pytest

from oran_lab.agent import EXPERIMENT_PROMPT, parse_grounded_proposal
from oran_lab.detector import NORMAL
from oran_lab.experiment import (
    ExperimentConfig, atomic_json, build_plan, preflight_resources, read_json, run_experiment, save_plan,
)
from oran_lab.experiment_cases import FINAL_CASES, PILOT_CASES, detections_for
from oran_lab.experiment_report import RUBRIC, aggregate, flatten, import_reviews, read_experiment


class FixtureRag:
    metadata = {"indice_sha256": "fixture", "tempo_abertura_s": 0}

    def retrieve(self, detection):
        return {
            "recuperados": [{"id": "fixture", "documento": "Documento de teste", "versao": "1",
                             "secao": "1.1", "paginas_pdf": [2], "texto": "Trecho exclusivamente sintético.",
                             "score": 0.9, "url": "https://example.org"}],
            "referencias_apresentadas": [], "referencias_citadas": None,
            "estado": "recuperado", "tempo_recuperacao_s": 0.01,
        }


class FixtureClient:
    def __init__(self, options, calls, *, mode="default"):
        self.options = options
        self.calls = calls
        self.mode = mode

    def metadata(self):
        return {"digest": "gerador-fixture"}

    def residency(self):
        return {"context_length": 8192}

    def request(self, path, payload):
        assert path == "/api/chat"
        user = json.loads(payload["messages"][-1]["content"])
        system = payload["messages"][0]["content"]
        self.calls.append((system, user, payload["options"], self))
        if self.mode == "interromper":
            raise KeyboardInterrupt()
        if system != EXPERIMENT_PROMPT:
            choice = {"ferramenta": "consultar_historico", "parametros": {"limite": 8}}
            if self.mode == "consulta-invalida":
                choice = {"ferramenta": "consultar_janela", "parametros": {"janela_id": 99}}
            return self.response(choice)
        if self.mode == "falha":
            raise ConnectionError("serviço indisponível")
        alert = user["detector"]["alerta_id"]
        register = user["detector"]["novo_alerta"] and self.mode != "sem-acao"
        return self.response({"acao": "registrar_alerta" if register else "nenhuma_acao",
                              "parametros": {"evento_id": alert} if register else {},
                              "justificativa": "Decisão da fixture sintética",
                              "referencias": ["R1"] if user["referencias_3gpp"] else []})

    @staticmethod
    def response(proposal):
        return 200, json.dumps({"done": True, "done_reason": "stop", "prompt_eval_count": 20,
                                "eval_count": 10, "message": {"role": "assistant", "content": json.dumps(proposal)}})


def experiment(tmp_path, methods, *, case="piloto-episodio", limit=12, mode="default", scope="controlada"):
    calls = []
    config = ExperimentConfig(mode=scope, cases=(case,), configurations=methods, max_calls=limit,
                              index=tmp_path / "ausente.json")
    directory = tmp_path / "exec"
    run_experiment(config, directory, client_factory=lambda opts: FixtureClient(opts, calls, mode=mode),
                   rag_factory=lambda _: FixtureRag())
    return directory, calls, config


def test_cases_and_final_plan_are_fixed(tmp_path):
    config = ExperimentConfig(phase="final", repetitions=3, max_calls=108, index=tmp_path / "ausente.json")
    plan = build_plan(config)
    assert build_plan(config) == plan
    assert len(PILOT_CASES) == 2 and len(FINAL_CASES) == 6
    assert len(plan["execucoes"]) == 90 and plan["max_chat_planejado"] == 108
    assert {job["seed"] for job in plan["execucoes"]} == {42, 43, 44}
    assert len({job["configuracao"] for job in plan["execucoes"][::5]}) > 1
    recovery = next(case for case in plan["casos"] if case["id"] == "recuperacao")
    assert recovery["entradas"]["6"]["estado_inicial"]["eventos"].keys() == {"alerta-5"}
    assert recovery["expectativas"]["6"]["situacao"] == NORMAL
    with pytest.raises(ValueError, match="autorização"):
        run_experiment(config, tmp_path / "final")


def test_controlled_prefix_does_not_read_future_ue_or_metrics():
    case = FINAL_CASES[2]
    target = case.targets[0]
    last = case.records[-1]
    changed = replace(case, records=(*case.records[:-1], (last[0], 999, 99999, 99999)))
    before, normal = detections_for(case, target)
    after, perturbed = detections_for(changed, target)
    assert len(before) == 15 and before.equals(after) and normal == perturbed


def test_equal_conditions_independent_sessions_and_rag_mcp(tmp_path):
    pytest.importorskip("mcp")
    directory, calls, _ = experiment(tmp_path, tuple("ABCDE"))
    final_calls = [entry for entry in calls if entry[0] == EXPERIMENT_PROMPT]
    assert len(calls) == 6 and len({call[3] for call in final_calls}) == 4
    assert len({json.dumps(call[2], sort_keys=True) for call in final_calls}) == 1
    evidence = [dict(call[1]) for call in final_calls]
    for item in evidence:
        item.pop("consultas_mcp")
        item.pop("referencias_3gpp")
    assert all(item == evidence[0] for item in evidence)
    records = {item[0]["configuracao"]: item for item in read_experiment(directory)}
    assert all(rec[2]["estado_anterior"] == records["A"][2]["estado_anterior"] for rec in records.values())
    c = flatten(*records["C"][:5])
    d = flatten(*records["D"][:5])
    assert c["concordancia_proposta"] and c["rag_decisao_com_citacao_validada"]
    assert d["mcp_uteis"] == 1 and d["chat_mcp"] == 1
    assert max(r["Register"] for r in records["D"][2]["agente"]["contexto_final"]["consultas_mcp"][0]
               ["resultado"]["registros"]) == 15


def test_invalid_mcp_selection_leaves_final_opportunity(tmp_path):
    pytest.importorskip("mcp")
    directory, calls, _ = experiment(tmp_path, ("D",), mode="consulta-invalida")
    row = flatten(*next(read_experiment(directory))[:5])
    assert len(calls) == 2 and row["mcp_invalidas"] == 1
    assert row["chat_decisao"] == 1 and row["concordancia_proposta"] and not row["fallback"]


def test_communication_failure_records_original_absence_and_fallback(tmp_path):
    directory, _, _ = experiment(tmp_path, ("B",), mode="falha")
    row = flatten(*next(read_experiment(directory))[:5])
    assert row["chat_falha_comunicacao"] == 1 and row["proposta_modelo_ausente"]
    assert row["fase_falha"] == "durante_execucao"
    assert row["fallback"] and row["concordancia_final"] and not row["concordancia_proposta"]
    assert not row["mudanca_modelo"]


def test_cycle_state_evolves_with_own_decisions(tmp_path):
    directory, calls, _ = experiment(tmp_path, ("B",), mode="sem-acao", scope="ciclo")
    records = list(read_experiment(directory))
    assert len(calls) == 6 and len({call[3] for call in calls}) == 1
    assert len(records) == 6 and not records[5][2]["estado_anterior"]["eventos"]
    assert not flatten(*records[4][:5])["concordancia_final"]


def test_budget_and_resume_never_duplicate_a_started_chat(tmp_path):
    config = ExperimentConfig(cases=("piloto-episodio",), configurations=("B", "C"), max_calls=1,
                              index=tmp_path / "ausente.json")
    calls = []
    directory = tmp_path / "retomada"
    factory = lambda opts: FixtureClient(opts, calls, mode="interromper")
    with pytest.raises(KeyboardInterrupt):
        run_experiment(config, directory, client_factory=factory, rag_factory=lambda _: FixtureRag())
    result = run_experiment(config, directory, resume=True,
                            client_factory=lambda opts: FixtureClient(opts, calls), rag_factory=lambda _: FixtureRag())
    assert result["chamadas_reservadas"] == 1 and len(calls) == 1
    rows = [flatten(*record[:5]) for record in read_experiment(directory)]
    assert {row["estado_execucao"] for row in rows} == {"interrompida", "pendente"}
    assert sum(row["chat_sem_retorno"] for row in rows) == 1
    with pytest.raises(ValueError, match="Plano diferente"):
        run_experiment(replace(config, max_calls=2), directory, resume=True)


def test_exports_and_imports_only_effective_human_scores(tmp_path):
    directory, _, _ = experiment(tmp_path, ("A", "B"))
    result = aggregate(directory)
    output = directory / "relatorios"
    assert result["oportunidades"] == result["avaliadas"] == 2
    assert (output / "resumo.png").is_file()
    for file in ("concordancia_proposta", "concordancia_final", "recusa_modelo", "fallback", "custos_computacionais"):
        assert (output / f"{file}.png").is_file()
    comparisons = read_json(output / "pareadas_por_caso.json")
    assert any(row["metrica"] == "concordancia_final" and row["n_pares_janela_semente"] == 1 for row in comparisons)
    template = output / "avaliacao-cega.csv"
    with template.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows and all("configuracao" not in row and all(row[key] == "" for key in RUBRIC) for row in rows)
    assert all(not json.loads(row["estado_inicial"])["eventos"] for row in rows)
    assert all(set(json.loads(row["acoes_disponiveis"])) == {"registrar_alerta", "nenhuma_acao"} for row in rows)
    with pytest.raises(ValueError, match="ainda"):
        import_reviews(directory, template)
    rows[0][RUBRIC[0]] = "2"
    filled = tmp_path / "notas.csv"
    with filled.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="avaliador"):
        import_reviews(directory, filled)
    assert import_reviews(directory, filled, evaluator="rev-01")["avaliacoes"] == 1
    assert import_reviews(directory, filled, evaluator="rev-01")["avaliacoes"] == 1
    assert import_reviews(directory, filled, evaluator="rev-02")["avaliacoes"] == 1
    summary = read_json(output / "avaliacoes_consolidadas.json")
    assert summary["avaliadores_identificados"] == ["rev-01", "rev-02"]
    pool = [r for r in summary["criterios"] if r["escopo"] == "todos" and r["configuracao"] == "todas"]
    assert (pool[0]["n_previstas"], pool[0]["n_pontuadas"], pool[0]["n_ausentes"]) == (4, 2, 2)
    assert (pool[0]["n_2"], pool[0]["media"]) == (2, 2)
    assert pool[-1]["grupo"] == "documental" and pool[-1]["n_previstas"] == 0 and pool[-1]["media"] is None


def test_justification_limit_validated_outside_simulator():
    value = {"acao": "nenhuma_acao", "parametros": {}, "justificativa": "á" * 301, "referencias": []}
    with pytest.raises(ValueError, match="300"):
        parse_grounded_proposal(json.dumps(value), [], {})
    value["justificativa"] = "á" * 300
    assert "referencias" not in parse_grounded_proposal(json.dumps(value), [], {})


def test_final_preflight_blocks_missing_generator_before_creating_any_session(tmp_path):
    config = ExperimentConfig(phase="final", cases=("estavel",), configurations=("B",))
    directory = tmp_path / "final"
    save_plan(config, directory)
    calls = []
    with pytest.raises(ValueError, match="bloqueada: ollama, gerador"):
        run_experiment(config, directory, authorize_final=True,
                       client_factory=lambda opts: FixtureClient(opts, calls))
    assert calls == [] and not (directory / "manifesto.json").exists()
    report = read_json(next((directory / "pre-verificacoes").glob("*.json")))
    assert report["estado"] == "bloqueada" and report["fase"] == "pre_execucao"
    assert set(report["verificacoes"]) == {"ollama", "gerador"}


def test_stale_final_plan_rejects_changed_git_revision_and_preserves_file(tmp_path, monkeypatch):
    config = ExperimentConfig(phase="final", cases=("estavel",), configurations=("B",))
    directory = tmp_path / "final"
    plan = save_plan(config, directory)
    monkeypatch.setattr("oran_lab.experiment.code_identity", lambda: {**plan["codigo"], "git": "outra-revisao"})
    with pytest.raises(ValueError, match="revisão Git"):
        run_experiment(config, directory, authorize_final=True,
                       client_factory=lambda _: pytest.fail("O plano antigo deve bloquear a sondagem"))
    assert read_json(directory / "plano.json") == plan


def test_preflight_conditionally_checks_index_and_embeddings(tmp_path):
    config = ExperimentConfig(phase="final", configurations=("C",), index=tmp_path / "indice.json")
    config.index.write_bytes(b"fixture")
    from oran_lab.dataset import dataset_digest

    digest = "b" * 64
    embedding = {"modelo": "embeddinggemma:latest", "digest": digest}
    resources = {"gerador": {"ollama": "fixture", "digest": "a" * 64}, "embeddings": embedding,
                 "rag": {"indice_sha256": "c" * 64, "indexacao": embedding.copy()}}
    plan = {"indice_arquivo_sha256": dataset_digest(config.index)}
    assert all(check["ok"] for check in preflight_resources(config, plan, resources).values())
    resources["rag"]["indexacao"]["digest"] = "d" * 64
    assert not preflight_resources(config, plan, resources)["indice_rag"]["ok"]
    config.index.unlink()
    assert not preflight_resources(config, plan, resources)["indice_rag"]["ok"]
    assert preflight_resources(ExperimentConfig(phase="final", configurations=("A",)), {}, {}) == {}


def test_report_distinguishes_zero_measured_from_absent(tmp_path):
    pytest.importorskip("mcp")
    directory, _, _ = experiment(tmp_path, ("E",))
    job, window, event, chats, execution, _ = next(read_experiment(directory))
    measured = flatten(job, window, event, chats, execution)
    assert measured["tempo_consultas_mcp_s"] >= 0 and measured["entrada_embeddings_tokens"] is None
    read = next(tool for tool in event["agente"]["mcp"]["ferramentas"] if tool["nome"] == "consultar_historico")
    read["tempo_s"] = 0
    event["agente"]["rag"]["metricas_embeddings"] = {"prompt_eval_count": 0}
    zero = flatten(job, window, event, chats, execution)
    assert zero["tempo_consultas_mcp_s"] == 0 and zero["entrada_embeddings_tokens"] == 0
    read.pop("tempo_s")
    assert flatten(job, window, event, chats, execution)["tempo_consultas_mcp_s"] is None


def test_review_consolidation_limits_documental_denominator_and_preserves_nonblank_scores(tmp_path):
    from oran_lab.experiment_report import consolidate_reviews

    output = tmp_path / "relatorios"
    atomic_json(output / "chave-avaliacao-local.json",
                {"x": {"configuracao": "B"}, "y": {"configuracao": "C"}})
    atomic_json(output / "avaliacao-referencias.json", [{"id": "y"}])
    for i, scores in enumerate(({"fidelidade_kpm": 0, "suporte_referencias": 2},
                                {"fidelidade_kpm": 1, "suporte_referencias": None})):
        atomic_json(tmp_path / "avaliacoes" / f"{i}.json",
                    {"data_utc": str(i), "avaliador": "rev",
                     "avaliacoes": {"y": {"pontuacoes": scores}}})
    consolidate_reviews(tmp_path, output)
    summary = read_json(output / "avaliacoes_consolidadas.json")
    pool = {r["criterio"]: r for r in summary["criterios"]
            if r["escopo"] == "todos" and r["configuracao"] == "todas"}
    assert pool["fidelidade_kpm"]["n_previstas"] == 2 and pool["fidelidade_kpm"]["media"] == 1
    assert pool["suporte_referencias"]["n_previstas"] == 1 and pool["suporte_referencias"]["media"] == 2
