"""Páginas de acompanhamento, leitura e avaliação científica no Streamlit."""

from datetime import datetime
import json
from time import monotonic

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .detector import NORMAL, PRB, SUSPECT, THROUGHPUT
from .experiment_report import RUBRIC
from .ui_experiments import interruption_requested, request_interruption
from .ui_records import (
    compare_records, elapsed, filter_rows, granular, next_window, plan_for, progress,
    recording_events, recordings, replay_prefix, result_rows, review_csv, review_material, review_mcp,
    reviewer_records, save_reviews, stored,
)
from .ui_runs import TERMINAL, active_experiment

MISSING = "—"
COMPONENTS = {
    "dataset": "Dataset", "preparacao": "Preparação", "replay": "Replay", "detector": "Detector",
    "selecao": "Seleção MCP", "mcp": "MCP", "rag": "RAG", "inferencia": "Inferência", "proposta": "Proposta",
    "validacao": "Validador", "execucao": "Simulador", "verificacao": "Verificador", "fallback": "Fallback",
    "janela": "Janela", "sessao": "Sessão", "experimento": "Experimento", "worker": "Worker",
}
STATES = {"desabilitada": ("Desabilitado", "#596c80"), "aguardando": ("Aguardando", "#526b83"),
          "iniciada": ("Em processamento", "#4babeb"), "concluida": ("Concluído", "#47d6bb"),
          "dispensada": ("Dispensado", "#a997e2"), "recusada": ("Recusado", "#fdba74"),
          "falha": ("Falha", "#fb8585"), "interrompida": ("Interrompido", "#f6d177")}
POSITIONS = {"dataset": (0, 0), "replay": (0, -1), "detector": (0, -2), "inferencia": (0, -3),
             "proposta": (0, -4), "validacao": (0, -5), "execucao": (0, -6), "verificacao": (0, -7),
             "selecao": (-1, -3), "mcp": (-1, -4), "rag": (1, -3), "fallback": (1, -5)}
EDGES = [*zip(tuple(POSITIONS)[:7], tuple(POSITIONS)[1:8], strict=True),
         ("inferencia", "selecao"), ("selecao", "mcp"), ("mcp", "proposta"), ("rag", "inferencia"),
         ("validacao", "fallback"), ("fallback", "execucao")]
SCORES = dict(zip(RUBRIC, ("Fidelidade aos KPMs", "Coerência operacional", "Correção técnica",
                          "Reconhecimento das limitações", "Pertinência das referências",
                          "Suporte das referências"), strict=True))
METRICS = {"concordancia_proposta": "Concordância da proposta", "concordancia_final": "Concordância final",
           "mudanca_verificada": "Mudanças verificadas", "mudanca_verificada_modelo": "Mudanças do modelo",
           "fallback": "Fallbacks", "mcp_validas": "Consultas MCP válidas", "mcp_invalidas": "Consultas MCP inválidas",
           "mcp_uteis": "Consultas MCP úteis", "mcp_redundantes": "Consultas MCP redundantes",
           "rag_recuperados": "RAG recuperados", "rag_apresentados": "RAG apresentados",
           "rag_citados_conferidos": "RAG citados conferidos", "tempo_s": "Tempo por janela (s)",
           "tempo_chat_s": "Tempo de chat (s)", "tempo_consultas_mcp_s": "Tempo MCP (s)",
           "tempo_recuperacao_s": "Tempo RAG (s)", "entrada_tokens": "Tokens de entrada", "saida_tokens": "Tokens de saída",
           "entrada_embeddings_tokens": "Tokens de embeddings"}
ERRORS = (ValueError, OSError, KeyError, TypeError)


def select_record(workspace, key, predicate=lambda _: True):
    entries = {key: record for key, record in recordings(workspace).items() if predicate(record)}
    if not entries:
        st.info("Nenhum registro compatível foi encontrado.")
        return None
    selected = st.selectbox("Execução", entries, format_func=lambda key: entries[key].title, key=f"draft/{key}")
    return entries[selected]


def message(event):
    data = event["dados"]
    detail = data.get("erro") or data.get("motivo") or data.get("justificativa") or data.get("ferramenta")
    if detail:
        return str(detail)
    if "proposta" in data and isinstance(data["proposta"], dict):
        return data["proposta"].get("acao", MISSING)
    return f"{COMPONENTS.get(event['componente'], event['componente'])} · {state_name(event['estado'])}"


def state_name(state):
    return STATES.get(state, (state, "#8299af"))[0]


def event_console(events, key):
    if not events:
        st.caption("Aguardando eventos gravados.")
        return
    with st.expander("Console de eventos"):
        columns = st.columns(4)
        filters = {}
        for col, field, text in zip(columns, ("sessao", "janela", "componente", "estado"),
                                    ("Sessões", "Janelas", "Componentes", "Estados"), strict=True):
            options = sorted({event[field] for event in events if event.get(field) is not None})
            filters[field] = col.multiselect(text, options, key=f"{key}-{field}")
        scoped = filter_rows(events, filters)
        first = next((datetime.fromisoformat(e["data_utc"]) for e in events if e.get("data_utc")), None)
        table = [{"Evento": e["seq"], "Hora UTC": e.get("data_utc"),
                  "Tempo relativo (s)": round((datetime.fromisoformat(e["data_utc"]) - first).total_seconds(), 3)
                  if e.get("data_utc") and first else None, "Sessão": e.get("sessao"), "Janela": e.get("janela"),
                  "Componente": COMPONENTS.get(e["componente"], e["componente"]),
                  "Estado": state_name(e["estado"]), "Mensagem": message(e)} for e in scoped[-500:]]
        st.caption(f"{len(scoped)} eventos filtrados. A tabela mostra até os 500 mais recentes.")
        st.dataframe(table, hide_index=True, width="stretch")
        if scoped:
            selected = st.selectbox("Detalhes do evento", [e["seq"] for e in reversed(scoped)], key=f"{key}-detail")
            st.json(next(e for e in scoped if e["seq"] == selected), expanded=False)


def component_events(events, current):
    if not current:
        return []
    session = current.get("sessao")
    window = current["janela"]
    if window is None and current["componente"] in ("sessao", "worker") and current["estado"] != "iniciada":
        window = next((event["janela"] for event in reversed(events)
                       if event.get("sessao") == session and event["janela"] is not None), None)
    return [event for event in events if event.get("sessao") == session and
            (event["janela"] == window or (event["janela"] is None and event["componente"] in ("dataset", "preparacao")))]


def circuit(events, arch, *, key, granular_available):
    if not granular_available:
        st.caption("O registro preservou decisões por janela e encerramentos por sessão.")
        return
    disabled = set()
    if arch == "A":
        disabled.add("fallback")
    if arch and arch not in ("C", "E"):
        disabled.add("rag")
    if arch and arch not in ("D", "E"):
        disabled.update(("selecao", "mcp"))
    observed = {node: [e for e in events if e["componente"] == node] for node in POSITIONS}
    chart = go.Figure()
    for left, right in EDGES:
        x, y = POSITIONS[left]
        x2, y2 = POSITIONS[right]
        if arch == "A" and "inferencia" in (left, right):
            if left == "detector" and right == "inferencia":
                x2, y2 = POSITIONS["proposta"]
            else:
                continue
        chart.add_annotation(x=x2, y=y2, ax=x, ay=y, xref="x", yref="y", axref="x", ayref="y",
                             showarrow=True, arrowhead=2, arrowsize=0.8, arrowcolor="#4b687e",
                             standoff=12, startstandoff=11,
                             opacity=.35 if disabled.intersection((left, right)) else 1)
    for node, (x, y) in POSITIONS.items():
        if arch == "A" and node == "inferencia":
            continue
        history = observed[node]
        state = history[-1]["estado"] if history else "desabilitada" if node in disabled else "aguardando"
        title = "Política Python" if node == "proposta" and arch == "A" else COMPONENTS[node]
        if node == "inferencia":
            title = "Agente · inferência"
        caption, color = STATES.get(state, (state, "#8299af"))
        count = sum(e["estado"] == "iniciada" for e in history)
        label = title + (f" ×{count}" if count > 1 else "")
        chart.add_scatter(x=[x], y=[y], mode="markers+text", text=[f"{label}<br><span style='color:{color}'>{caption}</span>"],
                          textposition="top center", textfont={"size": 12, "color": "#e5edf4"},
                          marker={"size": 17, "color": color, "line": {"color": "#122232", "width": 2}},
                          hovertext=[caption], hoverinfo="text", showlegend=False)
    chart.update_layout(height=485, margin={"l": 6, "r": 6, "t": 12, "b": 4},
                        xaxis={"range": [-1.65, 1.65], "visible": False, "fixedrange": True},
                        yaxis={"range": [-7.45, .9], "visible": False, "fixedrange": True},
                        paper_bgcolor="#122232", plot_bgcolor="#122232")
    st.plotly_chart(chart, width="stretch", config={"displayModeBar": False}, key=f"{key}-chart")
    options = [node for node in POSITIONS if observed[node]]
    if options:
        node = st.selectbox("Detalhes do componente", options, format_func=COMPONENTS.get, key=f"{key}-node")
        with st.expander(f"{len(observed[node])} registros · {COMPONENTS[node]}"):
            st.json(observed[node], expanded=False)


def timeline(events, *, key):
    windows = [event for event in events if event["componente"] == "janela"]
    if not windows:
        return
    with st.expander("Linha do tempo das decisões"):
        st.dataframe([{"Evento": e["seq"], "Sessão": e.get("sessao"), "Janela": e["janela"],
                       "Origem final": ((e["dados"].get("historico") or [{}])[-1]).get("origem"),
                       "Ação final": (((e["dados"].get("historico") or [{}])[-1]).get("proposta") or {}).get("acao")}
                      for e in windows[-500:]], hide_index=True)
        selected = st.selectbox("Decisão gravada", [e["seq"] for e in reversed(windows)], key=f"{key}-timeline")
        decisions(next(e["dados"] for e in windows if e["seq"] == selected))


def decisions(window):
    audit = window.get("agente") or {}
    history = window.get("historico") or []
    if audit:
        proposal = audit.get("proposta_original") or audit.get("proposta_modelo")
        if not proposal and audit.get("resposta_modelo"):
            st.code(audit["resposta_modelo"], language="json")
        if proposal:
            st.markdown("**Proposta original e justificativa declarada**")
            st.json(proposal, expanded=False)
        if audit.get("erro"):
            st.warning(audit["erro"])
        context = audit.get("contexto_final") or audit.get("contexto")
        if context:
            with st.expander("Evidências fornecidas ao agente"):
                st.json({k: v for k, v in context.items() if k != "referencias_3gpp"}, expanded=2)
        queries = [e for e in (audit.get("mcp") or {}).get("ferramentas", ())
                   if e.get("nome") in ("consultar_janela", "consultar_historico")]
        if queries:
            st.dataframe([{"Consulta MCP": e["nome"], "Tempo (s)": e.get("tempo_s"),
                           "Retorno": "Disponível" if e.get("resultado") is not None else e.get("erro")}
                          for e in queries], hide_index=True)
        rag = audit.get("rag") or {}
        hits = {hit["id"]: hit["texto"] for hit in rag.get("recuperados", [])}
        for ref in rag.get("referencias_apresentadas", []):
            with st.expander(f"{ref['ref']} · {ref['documento']} § {ref['secao']}"):
                st.caption(f"Versão {ref['versao']} · Cosseno {ref['score']:.3f}")
                st.text(hits.get(ref["id"], "Texto indisponível no registro."))
        if audit.get("fallback"):
            st.markdown("**Fallback Python**")
            st.json(audit["fallback"], expanded=False)
    if history:
        st.dataframe([{"Origem": e.get("origem"), "Ação": (e.get("proposta") or {}).get("acao"),
                       "Validação": e.get("validacao", {}).get("estado"),
                       "Motivo": e.get("validacao", {}).get("justificativa"),
                       "Execução": e.get("execucao", {}).get("estado"),
                       "Verificação": e.get("verificacao", {}).get("justificativa")} for e in history], hide_index=True)
    with st.expander("Auditoria JSON integral"):
        st.json(window, expanded=False)


@st.fragment(run_every="2s")
def live_experiment(workspace, record):
    plan = plan_for(record)
    manifest = stored(record.folder, "manifesto.json", {})
    snapshot = stored(record.folder, "status.json", {})
    cache = st.session_state.setdefault("research_diaries", {})
    events = cache.setdefault(record.title, [])
    events.extend(granular(record, events[-1]["seq"] if events else 0))
    totals, treatments, reserved, returned = progress(record, plan, events)
    latest = events[-1] if events else None
    sid = next((e["sessao"] for e in reversed(events) if e.get("sessao")), None)
    job = next((job for job in plan.get("execucoes", []) if job["id"] == sid), {})
    config = plan.get("configuracao", {})
    st.write(f"`{record.key}` · {config.get('mode', MISSING).replace('_', ' ')} · {state_name(snapshot.get('estado', 'aguardando'))}")
    if job:
        agent = job["tratamento"].get("agent") or {}
        window = next((e["janela"] for e in reversed(events) if e.get("sessao") == sid and e["janela"] is not None), None)
        st.caption(f"{job['configuracao']} · Arquitetura {job['tratamento']['architecture']} · "
                   f"{agent.get('model', 'Python')} · {job['caso']} · {sid} · "
                   f"Semente {job['seed']} · Repetição {job.get('repeticao', MISSING)} · Janela {window or MISSING}")
    runtime = elapsed(manifest, snapshot)
    a, b, c, d = st.columns(4)
    a.metric("Sessões concluídas", f"{totals.get('concluida', 0)} / {totals.get('planejadas', 0)}")
    b.metric("Janelas processadas", f"{totals.get('processadas', 0)} / {totals.get('janelas', 0)}")
    c.metric("Chat reservado / com retorno", f"{reserved} / {returned}")
    d.metric("Tempo decorrido", f"{runtime:.1f} s" if runtime is not None else MISSING)
    cap = config.get("max_chat", plan.get("max_chat"))
    st.caption(f"Pendentes {totals.get('pendente', 0)} · Em curso {totals.get('em_curso', 0)} · "
               f"Interrompidas {totals.get('interrompida', 0)} · Falhas {totals.get('falha', 0)} · "
               f"Orçamento disponível {max(0, cap - reserved) if cap is not None else MISSING}")
    for label, count, total in (("Sessões encerradas", sum(totals.get(k, 0) for k in TERMINAL), totals.get("planejadas")),
                                ("Oportunidades processadas", totals.get("processadas", 0), totals.get("janelas")),
                                ("Consumo de chat", reserved, cap)):
        if total:
            st.progress(min(count / total, 1.0), text=f"{label} · {count}/{total}")
    with st.expander("Progresso por tratamento"):
        st.dataframe([{"Tratamento": key, "Sessões planejadas": data["planejadas"],
                       "Concluídas": data.get("concluida", 0), "Pendentes": data.get("pendente", 0),
                       "Em curso": data.get("em_curso", 0), "Falhas": data.get("falha", 0),
                       "Interrompidas": data.get("interrompida", 0), "Janelas": data["processadas"],
                       "Janelas previstas": data["janelas"], "Chat reservado": data["reservas"]}
                      for key, data in treatments.items()], hide_index=True)
    if snapshot.get("erro"):
        st.error(snapshot["erro"])
    if snapshot and snapshot["estado"] not in TERMINAL:
        pending = interruption_requested(record.folder)
        if st.button("Interromper cooperativamente", disabled=pending):
            try:
                request_interruption(workspace, record.key)
                pending = True
            except ERRORS as error:
                st.warning(str(error))
        st.caption(("Interrupção solicitada. " if pending else "") +
                   "A janela atual é preservada. Uma chamada HTTP em curso pode precisar terminar.")
    observed = events if events else recording_events(record)[0]
    if events:
        active = next((e for e in reversed(events) if e.get("sessao")), latest)
        circuit(component_events(events, active), job.get("tratamento", {}).get("architecture"),
                key="live-circuit", granular_available=True)
    else:
        st.caption("A granularidade fica limitada aos arquivos existentes neste registro.")
    timeline(observed, key="live")
    event_console(observed, "live")


def central_page(workspace):
    st.title("Central de execução")
    st.caption("Acompanhamento ao vivo de experimentos configuráveis e consulta aos registros concluídos.")
    identifier = active_experiment(workspace)
    if identifier:
        st.session_state.setdefault("draft/central", f"Configurável/{identifier}")
    record = select_record(workspace, "central", lambda entry: entry.kind == "Configurável")
    if record:
        live_experiment(workspace, record)
        st.button("Consultar resultados deste experimento", on_click=go_to, args=("Resultados", "results", record))


def go_to(page, target, record):
    st.session_state["pagina"] = page
    st.session_state[f"draft/{target}"] = f"{record.kind}/{record.key}"


def summary_frame(frame):
    result = []
    for treatment, group in frame.groupby("configuracao", sort=True):
        output = {"Tratamento": treatment, "Oportunidades": len(group), "Processadas": int(group["avaliada"].sum()),
                  "Pendentes ou incompletas": int((~group["avaliada"]).sum()),
                  "Falhas de sessão (sessões)": group.loc[group["estado_execucao"].eq("falha"), "execucao"].nunique(),
                  "Falhas durante decisão": int(group["fase_falha"].eq("durante_execucao").sum()),
                  "Aceitas pelo validador": int(group["validacao_modelo"].eq("aceita").sum())
                  if treatment != "A" else None,
                  "Recusadas pelo validador": int(group["validacao_modelo"].eq("recusada").sum())
                  if treatment != "A" else None}
        for metric, label in METRICS.items():
            values = group[metric].dropna()
            if metric.startswith("concordancia"):
                output[label] = f"{int(values.sum())}/{len(values)}" if not values.empty else None
            elif metric.startswith("tempo_"):
                output[label] = float(values.median()) if not values.empty else None
            else:
                output[label] = float(values.sum()) if not values.empty else None
        result.append(output)
    return pd.DataFrame(result)


def results_page(workspace):
    st.title("Resultados")
    st.caption("Concordância com expectativas operacionais, custos e efeitos verificados no simulador.")
    first = select_record(workspace, "results")
    if not first:
        return
    rows = result_rows(first)
    if not rows:
        st.info("A execução ainda não tem oportunidades ou janelas registradas.")
        return
    filters = {}
    with st.expander("Filtrar oportunidades"):
        for col, key, title in zip(st.columns(3) * 2,
                                   ("modelo", "arquitetura", "configuracao", "caso", "seed", "repeticao"),
                                   ("Modelos", "Arquiteturas", "Tratamentos", "Cenários", "Sementes", "Repetições"),
                                   strict=True):
            options = sorted({row[key] for row in rows if row.get(key) is not None})
            filters[key] = col.multiselect(title, options, key=f"draft/res-{first.key}-{key}")
    filtered = filter_rows(rows, filters)
    if not filtered:
        st.info("Os filtros não retornaram oportunidades.")
        return
    frame = pd.DataFrame(filtered)
    summary = summary_frame(frame)
    if first.kind == "Etapa 7":
        method = plan_for(first).get("parametros", {})
        if method.get("mode") == "controlada":
            st.caption("Comparação entre tratamentos dentro do protocolo controlado desta execução.")
    a, b, c = st.columns(3)
    a.metric("Oportunidades processadas", f"{int(frame['avaliada'].sum())} / {len(frame)}")
    changes = frame["mudanca_verificada"].dropna()
    b.metric("Mudanças verificadas no simulador", int(changes.sum()) if not changes.empty else MISSING)
    fallbacks = frame["fallback"].dropna()
    c.metric("Fallbacks Python registrados", int(fallbacks.sum()) if not fallbacks.empty else MISSING)
    st.dataframe(summary, hide_index=True, width="stretch")
    metric = st.selectbox("Indicador no gráfico", METRICS, format_func=METRICS.get)
    figure = go.Figure()
    for treatment, group in frame.groupby("configuracao"):
        cases = group[["caso", metric]].dropna().groupby("caso")[metric].mean()
        if not cases.empty:
            figure.add_bar(x=cases.index, y=cases.values, name=treatment)
    if figure.data:
        figure.update_layout(barmode="group", yaxis_title=METRICS[metric], xaxis_title="Cenário")
        st.plotly_chart(figure, width="stretch")
        st.caption("Médias descritivas por tratamento e cenário. Repetições técnicas compartilham a mesma janela.")
    else:
        st.caption("Sem medidas registradas para o indicador.")
    with st.expander("Oportunidades e denominadores"):
        st.dataframe(frame, hide_index=True, width="stretch")
        st.download_button("Exportar CSV filtrado", frame.to_csv(index=False).encode("utf-8-sig"), "oportunidades.csv")
        st.download_button("Exportar JSON filtrado", frame.to_json(orient="records", force_ascii=False),
                           "oportunidades.json", "application/json")
    options = {key: record for key, record in recordings(workspace).items() if record != first}
    comparison = st.selectbox("Comparar com outra execução", options, index=None,
                              format_func=lambda key: options[key].title, key="draft/compare-run")
    if comparison:
        second = options[comparison]
        differences = compare_records(first, second)
        st.subheader("Comparação descritiva entre execuções")
        st.dataframe([{"Dimensão": item["dimensao"], "Compatibilidade": item["estado"]} for item in differences],
                     hide_index=True)
        with st.expander("Metadados de compatibilidade"):
            st.json(differences, expanded=False)
        a, b = st.columns(2)
        second_rows = result_rows(second)
        for col, record, table in ((a, first, summary), (b, second, summary_frame(pd.DataFrame(second_rows))
                                  if second_rows else pd.DataFrame())):
            col.markdown(f"**{record.title}**")
            col.dataframe(table, hide_index=True)
        st.caption("As execuções mantêm denominadores separados. O protocolo e as condições registradas delimitam as comparações controladas.")


def reviews_page(workspace):
    st.title("Avaliação científica")
    st.caption("Revisão humana da resposta e das evidências autorizadas. Os escores são preenchidos pelo avaliador.")
    record = select_record(workspace, "reviews", lambda entry: (entry.folder / "relatorios/avaliacao-cega.csv").is_file())
    if not record:
        return
    overlay, rows, refs = review_material(workspace, record)
    if not rows:
        st.info("Nenhuma resposta exportada para avaliação neste registro.")
        return
    by_id = {row["id"]: row for row in rows}
    evaluator = st.text_input("Identificador do avaliador", max_chars=100, key="draft/evaluator").strip()
    item = st.selectbox("Resposta anonimizada", by_id, key=f"draft/review-{record.key}")
    row = by_id[item]
    current = reviewer_records(workspace, record, evaluator) if evaluator else {}
    saved = current.get(item, {})
    st.caption(f"{len(rows)} respostas · {len(current)} com avaliação parcial ou completa deste avaliador · Janela {row['janela']}")
    with st.expander("Evidências KPM e estado autorizado", expanded=True):
        for label, key in (("Evidências", "evidencias"), ("Estado inicial", "estado_inicial"),
                           ("Ações disponíveis", "acoes_disponiveis")):
            st.markdown(f"**{label}**")
            st.json(json.loads(row[key]), expanded=False)
    answer = json.loads(row["resposta"])
    st.markdown(f"**Proposta** · {answer['acao']}")
    st.text(answer["justificativa"])
    st.json(answer["parametros"], expanded=False)
    with st.expander("Evidências adicionais consultadas via MCP"):
        evidence = review_mcp(record, item)
        if evidence:
            st.json(evidence, expanded=False)
        else:
            st.caption("Nenhuma evidência adicional registrada.")
    if item in refs:
        with st.expander("Avaliação documental"):
            st.json(refs[item], expanded=False)
    st.caption("Escala da rubrica · 0 inadequado, 1 parcial, 2 adequado. Campo vazio fica sem pontuação.")
    with st.form(f"review-{record.key}-{item}-{evaluator}"):
        notes = {}
        for criterion in RUBRIC if item in refs else RUBRIC[:-2]:
            if criterion == RUBRIC[-2]:
                st.subheader("Critérios documentais")
            values = (None, 0, 1, 2)
            notes[criterion] = st.selectbox(SCORES[criterion], values,
                                           index=values.index(saved.get("pontuacoes", {}).get(criterion)),
                                           format_func=lambda v: MISSING if v is None else str(v))
        comment = st.text_area("Comentário", value=saved.get("comentario", ""), max_chars=4000)
        revise = st.checkbox("Confirmo a revisão de uma nota ou comentário já salvo.")
        if st.form_submit_button("Salvar avaliação parcial", disabled=not evaluator, type="primary"):
            try:
                count = save_reviews(workspace, record, evaluator, review_csv([
                    {"id": item, "avaliador": evaluator, "comentario": comment, **notes}]), revise=revise)
                st.success("Lote salvo." if count else "O registro já contém esses valores.")
            except ERRORS as error:
                st.error(str(error))
    with st.expander("Importação e exportação"):
        export = [{"id": key, "avaliador": evaluator, "comentario": current.get(key, {}).get("comentario", ""),
                   **current.get(key, {}).get("pontuacoes", {})} for key in by_id]
        st.download_button("Exportar avaliações deste avaliador", review_csv(export), "avaliacoes.csv")
        with st.form("import-reviews"):
            upload = st.file_uploader("CSV avaliado", type=["csv"], max_upload_size=1)
            revise_upload = st.checkbox("Confirmo revisões de valores existentes neste lote.")
            if st.form_submit_button("Importar avaliações", disabled=not evaluator or upload is None):
                try:
                    count = save_reviews(workspace, record, evaluator, upload.getvalue(), revise=revise_upload)
                    st.success(f"{count} respostas novas ou revisadas.")
                except ERRORS as error:
                    st.error(str(error))
        consolidated = overlay / "relatorios/avaliacoes_consolidadas.csv"
        if consolidated.is_file():
            st.download_button("Exportar consolidação", consolidated.read_bytes(), "avaliacoes_consolidadas.csv")


def kpm_charts(events, key):
    points, markers = {}, []
    previous = None
    for e in events:
        if e["componente"] == "replay":
            points.update({row["Register"]: row for row in e["dados"].get("pontos", [])})
        detection = e["dados"].get("deteccao")
        if detection:
            position = detection["janela"]["registros"][-1]
            situation = detection["situacao"]
            if situation == SUSPECT and previous != SUSPECT:
                markers.append((position, "Suspeita", "#fdba74"))
            if situation == NORMAL and previous == SUSPECT:
                markers.append((position, "Recuperação observada", "#67e8b6"))
            previous = situation
        if e["componente"] == "janela" and points:
            if any(entry["execucao"]["estado"] == "executada" and (entry.get("proposta") or {}).get("acao") == "registrar_alerta"
                   for entry in e["dados"].get("historico", [])):
                markers.append((max(points), "Alerta simulado", "#f78991"))
    if not points:
        st.caption("Ainda não há amostras de KPM gravadas neste prefixo.")
        return
    for col, field, title, color in zip(st.columns(2), (THROUGHPUT, PRB), ("Throughput UL", "PRB UL"),
                                        ("#4ce4cf", "#79afff"), strict=True):
        x, y = [], []
        for register in sorted(points):
            if x and register > x[-1] + 1:
                x.append(register - 1)
                y.append(None)
            x.append(register)
            y.append(points[register].get(field))
        figure = go.Figure(go.Scatter(x=x, y=y, mode="lines+markers", line={"color": color}, connectgaps=False))
        for position, label, marker in markers:
            figure.add_vline(x=position, line_color=marker, line_dash="dot", annotation_text=label,
                             annotation_position="top left" if label == "Alerta simulado" else "top right")
        figure.update_layout(title=title, xaxis_title="Register", yaxis_title="Valor registrado", height=330,
                             margin={"l": 14, "r": 14, "t": 62, "b": 42})
        col.plotly_chart(figure, width="stretch", key=f"{key}-{field}")


@st.fragment(run_every="0.5s")
def playback(events, is_granular, arch, context, expanded):
    player = st.session_state.setdefault("recording_players", {}).setdefault(context, {"index": 0, "playing": False, "tick": 0.0})
    controls = st.columns(4)

    def play():
        if player["index"] >= len(events):
            player["index"] = 0
        player.update(playing=True, tick=monotonic())

    def seek(index):
        player.update(index=index, playing=False)

    with controls[0]:
        st.button("Iniciar" if player["index"] == 0 else "Continuar", disabled=player["playing"], on_click=play)
        st.button("Pausar", disabled=not player["playing"], on_click=player.update, kwargs={"playing": False})
    with controls[1]:
        st.button("Reiniciar", on_click=seek, args=(0,))
        st.button("Retroceder evento", disabled=player["index"] == 0, on_click=seek, args=(player["index"] - 1,))
    with controls[2]:
        st.button("Avançar evento", disabled=player["index"] >= len(events), on_click=seek, args=(player["index"] + 1,))
        st.button("Avançar janela", disabled=player["index"] >= len(events), on_click=seek,
                  args=(next_window(events, player["index"]),))
    speed = controls[3].selectbox("Velocidade", (0.5, 1.0, 2.0, 4.0), index=1, format_func=lambda v: f"{v:g}×")
    with st.expander("Ir para evento ou janela"):
        a, b = st.columns(2)
        target = a.number_input("Posição do evento", 1, len(events), value=1)
        if a.button("Ir ao evento"):
            player.update(index=target, playing=False)
        windows = list(dict.fromkeys(e["janela"] for e in events if e["componente"] == "janela"))
        if windows:
            window = b.selectbox("Número da janela", windows)
            if b.button("Ir à janela"):
                target = next(n for n, e in enumerate(events, 1) if e["componente"] == "janela" and e["janela"] == window)
                player.update(index=target, playing=False)
    if player["playing"]:
        elapsed_time = monotonic() - player["tick"]
        steps = int(elapsed_time * speed)
        if steps:
            player["index"] = min(len(events), player["index"] + steps)
            player["tick"] += steps / speed
            if player["index"] == len(events):
                player["playing"] = False
    prefix = replay_prefix(events, player["index"])
    st.progress(len(prefix) / len(events), text=f"Eventos revelados · {len(prefix)}/{len(events)}")
    current = prefix[-1] if prefix else None
    if current:
        st.caption(f"Evento {current['seq']} · Janela {current['janela'] or MISSING} · {message(current)}")
    kpm_charts(prefix, context)
    if expanded:
        circuit(component_events(prefix, current), arch, key=f"{context}-play", granular_available=is_granular)
    else:
        with st.expander("Arquitetura observada", expanded=True):
            circuit(component_events(prefix, current), arch, key=f"{context}-play", granular_available=is_granular)
    complete = next((e for e in reversed(prefix) if e["componente"] == "janela"), None)
    if complete:
        st.subheader(f"Decisão da janela {complete['janela']}")
        decisions(complete["dados"])
    if not expanded:
        timeline(prefix, key="playback")
        event_console(prefix, "playback")


def presentation_page(workspace):
    st.title("Modo apresentação")
    st.caption("Reprodução gravada · KPMs são históricos ou sintéticos. Alertas e mudanças pertencem ao simulador.")
    record = select_record(workspace, "presentation")
    if not record:
        return
    events, is_granular = recording_events(record)
    manifest = stored(record.folder, "manifesto.json", {})
    plan = plan_for(record)
    configuration = manifest.get("configuracao", {})
    arch = configuration.get("architecture")
    if plan.get("execucoes"):
        cases = list(dict.fromkeys(job["caso"] for job in plan["execucoes"]))
        case = st.selectbox("Cenário", cases, key=f"draft/pres-case-{record.key}")
        jobs = {job["id"]: job for job in plan["execucoes"] if job["caso"] == case}
        sid = st.selectbox("Sessão gravada", jobs, format_func=lambda s: f"{s} · {jobs[s]['configuracao']}",
                           key=f"draft/pres-session-{record.key}-{case}")
        arch = jobs[sid].get("tratamento", {}).get("architecture", jobs[sid]["configuracao"])
        events = [e for e in events if e.get("sessao") == sid]
    else:
        sid = "operacional"
        st.caption(f"Fonte · {configuration.get('source', MISSING)} · Arquitetura {arch or MISSING}")
    expanded = st.toggle("Visualização ampliada", help="Recolha a barra lateral para ampliar a área dos gráficos.")
    if events:
        playback(events, is_granular, arch, f"play-{record.title}-{sid}", expanded)
    else:
        st.info("A sessão selecionada ainda não possui eventos gravados.")
    with st.expander("Conceitos da demonstração"):
        st.write("O replay libera registros históricos ou sintéticos por janela. O detector sinaliza quedas sob regras "
                 "de referência e cobertura. MCP consulta evidências locais. RAG fornece trechos documentais. "
                 "O simulador aplica apenas ações validadas. Variações de throughput pertencem à série reproduzida.")
