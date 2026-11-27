"""Leitura dos eventos, estatística descritiva e avaliação humana da Etapa 7."""

import csv
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from .agent import build_context
from .experiment import atomic_json, now, read_json, run_lock
from .experiment_cases import LIMITS
from .rag import digest_json

RUBRIC = ("fidelidade_kpm", "coerencia_operacional", "correcao_tecnica", "limitacoes",
          "pertinencia_referencias", "suporte_referencias")
METRICS = ("concordancia_proposta", "concordancia_final", "tempo_s", "tempo_chat_s",
           "entrada_tokens", "saida_tokens", "tempo_recuperacao_s", "concordancia_com_contexto_rag",
           "tempo_consultas_mcp_s", "entrada_embeddings_tokens", "recusa_modelo", "fallback")


def matches(proposal, expected):
    if expected is None:
        return None
    return isinstance(proposal, dict) and all(proposal.get(key) == expected[key] for key in ("acao", "parametros"))


def tool_classification(audit, window, base_context):
    if audit is None:
        return []
    records = []
    for entry in audit.get("ferramentas", []):
        name = entry["nome"]
        if name in (None, "solicitar_acao"):
            continue
        result = entry.get("resultado")
        valid = result is not None
        useful = False
        if valid and name == "consultar_janela":
            useful = result["janela"]["id"] < window
        if valid and name == "consultar_historico":
            first = base_context["janela"]["primeiro_register"]
            useful = any(row.get("Register", first) < first and
                         any(value is not None for key, value in row.items() if key != "Register")
                         for row in result["registros"])
        records.append({"ferramenta": name, "valida": valid, "util": useful if valid else None,
                        "redundante": (not useful) if valid else None, "tempo_s": entry.get("tempo_s")})
    return records


def chat_by_window(folder):
    windows = {}
    for start in sorted((folder / "chat").glob("*-inicio.json")):
        attempt = read_json(start)
        payload = json.loads(attempt["payload"]["messages"][-1]["content"])
        window = payload["janela"]["id"]
        end = start.with_name(start.name.replace("-inicio.json", "-fim.json"))
        result = read_json(end) if end.is_file() else None
        windows.setdefault(window, []).append({"tipo": attempt["tipo"], "retorno": result})
    return windows


def read_experiment(directory):
    """Obtém o plano e todas as oportunidades, inclusive pendentes e interrompidas."""
    plan = read_json(directory / "plano.json")
    if plan.get("sha256") != digest_json({key: value for key, value in plan.items() if key != "sha256"}):
        raise ValueError("O plano foi alterado depois de salvo")
    manifest_file = directory / "manifesto.json"
    manifest = read_json(manifest_file) if manifest_file.exists() else {"id": plan["sha256"]}
    if manifest_file.exists() and manifest.get("plano_sha256") != plan["sha256"]:
        raise ValueError("O manifesto pertence a outro plano")
    for job in plan["execucoes"]:
        folder = directory / "execucoes" / job["id"]
        chats = chat_by_window(folder)
        end = folder / "resultado.json"
        execution = read_json(end) if end.exists() else {"estado": "parcial" if chats else "pendente"}
        for window in job["janelas"]:
            path = folder / "eventos" / f"janela-{window:04d}.json"
            event = read_json(path) if path.is_file() else None
            yield job, window, event, chats.get(window, []), execution, manifest["id"]


def flatten(job, window, event, chats, execution):
    decision = (event or {}).get("agente") or {}
    history = (event or {}).get("historico", [])
    expected = (event or {}).get("expectativa")
    original = decision.get("proposta_original")
    original = original if isinstance(original, dict) and "acao" in original else None
    final = history[-1] if history else None
    model_entry = next((item for item in history if item["id"] == decision.get("historico_modelo")), None)
    rag = decision.get("rag") or {}
    mcp = decision.get("mcp")
    tools = tool_classification(mcp, window, decision.get("contexto"))
    selections = decision.get("inferencias_consulta", [])
    communication_count = sum(item["retorno"] is not None and (
        item["retorno"].get("status") != 200) for item in chats)
    invalid_selection = bool(decision.get("erro_consulta_mcp") and selections
                             and not tools and not any(s.get("erro_comunicacao") for s in selections))
    model_calls = [*selections, decision]

    def sum_metric(key):
        values = [(call.get("metricas_ollama") or {}).get(key) for call in model_calls]
        numbers = [value for value in values if type(value) is int]
        return sum(numbers) if numbers else None

    evaluated = event is not None
    is_model = job["configuracao"] != "A"
    is_rag = job["configuracao"] in ("C", "E")
    is_mcp = job["configuracao"] in ("D", "E")
    attempted_final = any(item["tipo"] == "decisao" for item in chats)
    rag_cited = rag.get("referencias_citadas")
    has_excerpts = bool(rag.get("referencias_apresentadas"))
    tool_times = [t["tempo_s"] for t in tools if type(t["tempo_s"]) in (int, float)]
    failure_phase = execution.get("fase_falha")
    if decision.get("erro") or decision.get("erro_consulta_mcp") or rag.get("erro") or communication_count:
        failure_phase = "durante_execucao"
    return {
        "execucao": job["id"], "caso": job["caso"], "configuracao": job["configuracao"], "seed": job["seed"],
        "janela": window, "estado_execucao": execution["estado"], "avaliada": evaluated,
        "erro_execucao": execution.get("erro"), "fase_falha": failure_phase,
        "expectativa_acao": (expected or {}).get("acao"),
        "proposta_acao": (original or {}).get("acao"),
        "concordancia_proposta": matches(original, expected) if evaluated and is_model else None,
        "concordancia_condicional": matches(original, expected) if original is not None else None,
        "concordancia_final": matches(final["proposta"], expected) if final else None,
        "proposta_modelo_ausente": (original is None) if is_model and evaluated else None,
        "decisao_final_nao_consultada": (not attempted_final) if is_model and evaluated else None,
        "validacao_modelo": (model_entry or {}).get("validacao", {}).get("estado"),
        "recusa_modelo": model_entry["validacao"]["estado"] == "recusada" if model_entry else None,
        "validacao_final": (final or {}).get("validacao", {}).get("estado"),
        "execucao_final": (final or {}).get("execucao", {}).get("estado"),
        "acao_final": (final or {}).get("proposta", {}).get("acao"), "origem_final": (final or {}).get("origem"),
        "mudanca_modelo": (final["origem"] == "ollama" and final["execucao"]["estado"] == "executada")
        if final and is_model else None,
        "fallback": (final["origem"] == "fallback_python") if final and is_model else None,
        "erro_decisao": decision.get("erro"), "erro_mcp": decision.get("erro_consulta_mcp"),
        "chat_reservadas": len(chats), "chat_sem_retorno": sum(item["retorno"] is None for item in chats),
        "chat_falha_comunicacao": communication_count,
        "chat_decisao": sum(item["tipo"] == "decisao" for item in chats),
        "chat_mcp": sum(item["tipo"] == "selecao_mcp" for item in chats),
        "mcp_classificacao": json.dumps(tools, ensure_ascii=False) if is_mcp and evaluated else None,
        "mcp_validas": sum(t["valida"] for t in tools) if is_mcp and evaluated else None,
        "mcp_invalidas": sum(not t["valida"] for t in tools) + int(invalid_selection) if is_mcp and evaluated else None,
        "mcp_uteis": sum(t["util"] is True for t in tools) if is_mcp and evaluated else None,
        "mcp_redundantes": sum(t["redundante"] is True for t in tools) if is_mcp and evaluated else None,
        "rag_estado": (rag.get("estado") or "nao_alcancado") if is_rag and evaluated else None,
        "rag_recuperados": len(rag.get("recuperados", [])) if is_rag and evaluated else None,
        "rag_apresentados": len(rag.get("referencias_apresentadas", [])) if is_rag and evaluated else None,
        "rag_citados_conferidos": len(rag_cited) if rag.get("referencias_validas") else (0 if is_rag and evaluated else None),
        "rag_decisao_com_citacao_validada": bool(rag.get("decisao_com_citacao_validada")) if is_rag and evaluated else None,
        "rag_sem_contexto_apresentado": not has_excerpts if is_rag and evaluated else None,
        "concordancia_com_contexto_rag": matches(original, expected) if has_excerpts else None,
        "tempo_s": (event or {}).get("tempo_s"), "tempo_recuperacao_s": rag.get("tempo_recuperacao_s"),
        "tempo_consultas_mcp_s": sum(tool_times) if tool_times else None,
        "n_consultas_mcp_com_tempo": len(tool_times) if is_mcp and evaluated else None,
        "entrada_embeddings_tokens": (rag.get("metricas_embeddings") or {}).get("prompt_eval_count"),
        "tempo_chat_s": sum(d.get("tempo_chamada_s") or 0 for d in model_calls) if chats and evaluated else None,
        "entrada_tokens": sum_metric("prompt_eval_count"), "saida_tokens": sum_metric("eval_count"),
        "entrada_em_cache_tokens": sum_metric("prompt_eval_cached_count"),
    }


def description(frame):
    rows = []
    for method, group in frame.groupby("configuracao", sort=True):
        for metric in (*METRICS, "concordancia_condicional"):
            subset = group[["caso", metric]].dropna()
            per_case = subset.groupby("caso")[metric].mean()
            rows.append({
                "configuracao": method, "metrica": metric, "n_planejadas": len(group),
                "n_avaliadas": int(group["avaliada"].sum()), "n_com_medida": len(subset), "n_casos": len(per_case),
                "media_das_medias_por_caso": per_case.mean(), "mediana_das_medias_por_caso": per_case.median(),
                "desvio_padrao_entre_casos": per_case.std(), "min_media_caso": per_case.min(),
                "max_media_caso": per_case.max(),
            })
    return pd.DataFrame(rows)


def paired(frame):
    rows = []
    for base, treatment in (("A", "B"), ("A", "C"), ("A", "D"), ("A", "E"),
                            ("B", "C"), ("B", "D"), ("B", "E"), ("C", "E"), ("D", "E")):
        for metric in ("concordancia_proposta", "concordancia_final", "tempo_chat_s", "entrada_tokens"):
            a = frame.loc[frame.configuracao == base, ["caso", "janela", "seed", metric]]
            b = frame.loc[frame.configuracao == treatment, ["caso", "janela", "seed", metric]]
            pairs = a.merge(b, on=["caso", "janela", "seed"], validate="one_to_one").dropna()
            for case, group in pairs.groupby("caso"):
                differences = group[f"{metric}_y"].astype(float) - group[f"{metric}_x"].astype(float)
                rows.append({"base": base, "tratamento": treatment, "metrica": metric, "caso": case,
                             "n_pares_janela_semente": len(group), "diferenca_media": differences.mean(),
                             "diferenca_mediana": differences.median(),
                             "desvio_dos_pares": differences.std()})
    return pd.DataFrame(rows, columns=["base", "tratamento", "metrica", "caso", "n_pares_janela_semente",
                                       "diferenca_media", "diferenca_mediana", "desvio_dos_pares"])


def write_exports(values, directory):
    output = directory / "relatorios"
    output.mkdir(exist_ok=True)
    frame = pd.DataFrame([flatten(*item[:5]) for item in values])
    stats = description(frame)
    pairs = paired(frame)
    for name, table in (("decisoes", frame), ("descritivas", stats), ("pareadas_por_caso", pairs)):
        table.to_csv(output / f"{name}.csv", index=False, encoding="utf-8")
        atomic_json(output / f"{name}.json", json.loads(table.to_json(orient="records", force_ascii=False)))
    counted = frame.assign(
        aceita_modelo=frame["validacao_modelo"].eq("aceita"), recusa_modelo=frame["validacao_modelo"].eq("recusada"),
        aceita_sem_efeito=frame["validacao_final"].eq("aceita") & frame["execucao_final"].eq("nao_executada"),
    )
    indicators = ("chat_decisao", "chat_mcp", "proposta_modelo_ausente", "decisao_final_nao_consultada",
                  "aceita_modelo", "recusa_modelo", "aceita_sem_efeito", "mudanca_modelo", "fallback",
                  "mcp_validas", "mcp_invalidas", "mcp_uteis", "mcp_redundantes", "rag_sem_contexto_apresentado",
                  "rag_apresentados", "rag_citados_conferidos", "rag_decisao_com_citacao_validada")
    grouped = counted.groupby("configuracao")
    counts = grouped.agg(
        oportunidades=("janela", "size"), avaliadas=("avaliada", "sum"),
        chat_reservadas=("chat_reservadas", "sum"), sem_retorno=("chat_sem_retorno", "sum"),
        falhas_comunicacao=("chat_falha_comunicacao", "sum"))
    counts = counts.join(grouped[list(indicators)].sum(min_count=1))
    counts.to_csv(output / "contagens.csv", encoding="utf-8")
    atomic_json(output / "contagens.json", json.loads(counts.reset_index().to_json(orient="records")))
    export_reviews(values, output)
    consolidate_reviews(directory, output)
    plot(stats, output)
    return {"oportunidades": len(frame), "avaliadas": int(frame["avaliada"].sum()),
            "chat_reservadas": int(frame["chat_reservadas"].sum()), "pasta": str(output)}


def plot(stats, output):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    for ax, metric, label in zip(axes, ("concordancia_final", "tempo_chat_s"),
                                 ("Concordância da decisão final", "Tempo de chat (s)"), strict=True):
        data = stats[stats.metrica == metric].dropna(subset=["media_das_medias_por_caso"])
        ax.bar(data["configuracao"], data["media_das_medias_por_caso"])
        ax.set_title(label)
        ax.set_xlabel("Configuração")
        if metric == "concordancia_final":
            ax.set_ylim(0, 1)
    fig.suptitle("Médias por caso, com o mesmo peso para cada caso")
    fig.savefig(output / "resumo.png", dpi=140)
    plt.close(fig)

    def draw(ax, metric, title, proportion=False):
        data = stats[stats.metrica == metric].dropna(subset=["media_das_medias_por_caso"])
        ax.bar(data["configuracao"], data["media_das_medias_por_caso"])
        for pos, n in enumerate(data["n_com_medida"]):
            ax.annotate(f"n={n}", (pos, 0), xytext=(0, 3), textcoords="offset points", ha="center")
        if data.empty:
            ax.text(0.5, 0.5, "Sem medida disponível", ha="center", transform=ax.transAxes)
        ax.set_title(title)
        ax.set_xlabel("Configuração")
        if proportion:
            ax.set_ylim(0, 1.05)

    for metric, title in (("concordancia_proposta", "Concordância das propostas originais"),
                          ("concordancia_final", "Concordância das decisões finais"),
                          ("recusa_modelo", "Recusas entre propostas validadas do modelo"),
                          ("fallback", "Fallbacks entre decisões avaliadas do agente")):
        fig, ax = plt.subplots(figsize=(6, 4), layout="constrained")
        draw(ax, metric, title, proportion=True)
        fig.savefig(output / f"{metric}.png", dpi=140)
        plt.close(fig)

    fig, axes = plt.subplots(2, 3, figsize=(12, 7), layout="constrained")
    costs = (("tempo_chat_s", "Chat (s)"), ("tempo_consultas_mcp_s", "Consultas MCP (s)"),
             ("tempo_recuperacao_s", "Recuperação RAG (s)"), ("entrada_tokens", "Entrada de chat (tokens)"),
             ("saida_tokens", "Saída de chat (tokens)"), ("entrada_embeddings_tokens", "Embeddings (tokens)"))
    for ax, (metric, title) in zip(axes.flat, costs, strict=True):
        draw(ax, metric, title)
    fig.suptitle("Custos observados · médias por caso")
    fig.savefig(output / "custos_computacionais.png", dpi=140)
    plt.close(fig)


def export_reviews(values, output):
    reviews, references, mapping = [], [], {}
    for job, window, event, _, _, run_id in values:
        if event is None:
            continue
        audit = event.get("agente") or {}
        candidate = audit.get("proposta_original")
        if job["configuracao"] == "A":
            candidate = event["historico"][-1]["proposta"]
        if not isinstance(candidate, dict) or not {"acao", "parametros", "justificativa"} <= candidate.keys():
            continue
        blind = digest_json([run_id, job["id"], window])[:16]
        answer = {key: candidate[key] for key in ("acao", "parametros", "justificativa")}
        state = event["estado_anterior"]
        context = build_context(event["detector"], state, LIMITS)
        actions = {name: context["acoes"][name] for name in context["acoes_com_alvo_disponivel"]}
        reviews.append({"id": blind, "caso": job["caso"], "janela": window,
                        "evidencias": json.dumps(event["detector"], ensure_ascii=False),
                        "estado_inicial": json.dumps(state, ensure_ascii=False),
                        "acoes_disponiveis": json.dumps(actions, ensure_ascii=False),
                        "resposta": json.dumps(answer, ensure_ascii=False),
                        **{field: "" for field in RUBRIC}, "avaliador": "", "comentario": ""})
        cite = (audit.get("rag") or {}).get("referencias_citadas")
        presented = (audit.get("contexto_final") or {}).get("referencias_3gpp", [])
        if presented:
            references.append({"id": blind, "citadas": cite, "apresentadas": presented})
        mapping[blind] = {"execucao": job["id"], "configuracao": job["configuracao"], "janela": window}
    fields = ("id", "caso", "janela", "evidencias", "estado_inicial", "acoes_disponiveis",
              "resposta", *RUBRIC, "avaliador", "comentario")
    pd.DataFrame(sorted(reviews, key=lambda row: row["id"]), columns=fields).to_csv(
        output / "avaliacao-cega.csv", index=False, encoding="utf-8-sig")
    atomic_json(output / "avaliacao-referencias.json", sorted(references, key=lambda row: row["id"]))
    atomic_json(output / "chave-avaliacao-local.json", mapping)


def aggregate(directory):
    """Gera tabelas e arquivos de revisão para uma única execução."""
    with run_lock(directory):
        return write_exports(list(read_experiment(directory)), directory)


def consolidate_reviews(directory, output):
    known = read_json(output / "chave-avaliacao-local.json")
    reference_ids = {row["id"] for row in read_json(output / "avaliacao-referencias.json")}
    batches = [(file.stem, read_json(file)) for file in (directory / "avaliacoes").glob("*.json")]
    ratings = {}
    for batch_id, batch in sorted(batches, key=lambda item: (item[1]["data_utc"], item[0])):
        reviewer = batch.get("avaliador")
        key = (reviewer, None if reviewer else batch_id)
        scores = ratings.setdefault(key, {})
        for item_id, rating in batch["avaliacoes"].items():
            for criterion, score in rating["pontuacoes"].items():
                if score is not None:
                    scores[item_id, criterion] = score

    groups = {"todas": set(known)}
    for item_id, source in known.items():
        groups.setdefault(source["configuracao"], set()).add(item_id)
    scopes = [("todos", None, None, list(ratings.values()))]
    scopes.extend(("individual", reviewer, legacy, [scores])
                  for (reviewer, legacy), scores in ratings.items())
    rows = []
    for scope, reviewer, legacy, reviewers in scopes:
        for configuration, items in groups.items():
            for criterion in RUBRIC:
                documental = criterion in RUBRIC[-2:]
                eligible = items & reference_ids if documental else items
                scores = [given[item, criterion] for given in reviewers for item in eligible
                          if (item, criterion) in given]
                expected = len(eligible) * len(reviewers)
                rows.append({"escopo": scope, "avaliador": reviewer, "lote_sem_identificacao": legacy,
                             "configuracao": configuration, "grupo": "documental" if documental else "principal",
                             "criterio": criterion, "n_itens_elegiveis": len(eligible), "n_previstas": expected,
                             "n_pontuadas": len(scores), "n_ausentes": expected - len(scores),
                             "n_0": scores.count(0), "n_1": scores.count(1), "n_2": scores.count(2),
                             "media": sum(scores) / len(scores) if scores else None})
    pd.DataFrame(rows).to_csv(output / "avaliacoes_consolidadas.csv", index=False, encoding="utf-8")
    atomic_json(output / "avaliacoes_consolidadas.json",
                {"avaliadores_identificados": sorted(reviewer for reviewer, _ in ratings if reviewer),
                 "lotes_sem_identificacao": sorted(legacy for _, legacy in ratings if legacy),
                 "criterios": rows})


def import_reviews(directory, path: Path, *, evaluator=None):
    """Importa avaliações sem sobrescrever lotes já registrados."""
    with run_lock(directory):
        output = directory / "relatorios"
        known = read_json(output / "chave-avaliacao-local.json")
        reference_ids = {item["id"] for item in read_json(output / "avaliacao-referencias.json")}
        imported = {}
        reviewers = set()
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not set(("id", *RUBRIC)) <= set(reader.fieldnames or []):
                raise ValueError("Colunas da rubrica ausentes")
            for row in reader:
                key = row["id"]
                if key not in known or key in imported:
                    raise ValueError("ID de avaliação desconhecido ou duplicado")
                scores = {}
                for field in RUBRIC:
                    value = (row.get(field) or "").strip()
                    if (value not in ("", "0", "1", "2")
                            or (value and field in RUBRIC[-2:] and key not in reference_ids)):
                        raise ValueError(f"Pontuação inválida em {key}/{field}")
                    scores[field] = int(value) if value else None
                imported[key] = {"pontuacoes": scores, "comentario": row.get("comentario", "")}
                if any(value is not None for value in scores.values()) or imported[key]["comentario"]:
                    reviewer = (row.get("avaliador") or "").strip()
                    if reviewer:
                        reviewers.add(reviewer)
        completed = {key: record for key, record in imported.items()
                     if any(value is not None for value in record["pontuacoes"].values()) or record["comentario"]}
        if not completed:
            raise ValueError("O CSV ainda não contém avaliações preenchidas")
        if evaluator and evaluator.strip():
            reviewers.add(evaluator.strip())
        if len(reviewers) != 1:
            raise ValueError("Identifique um único avaliador por lote com --avaliador ou a coluna avaliador")
        target = directory / "avaliacoes" / f"{uuid4().hex}.json"
        atomic_json(target, {"data_utc": now(), "origem": path.name,
                             "avaliador": reviewers.pop(), "avaliacoes": completed})
        consolidate_reviews(directory, output)
        return {"pasta": str(target), "avaliacoes": len(completed)}
