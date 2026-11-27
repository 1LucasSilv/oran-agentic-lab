"""Páginas Streamlit da Etapa 7.1.1."""

from http.client import HTTPException
from pathlib import Path
from uuid import uuid4

import plotly.graph_objects as go
import pandas as pd
import streamlit as st

from oran_lab.detector import INSUFFICIENT, NORMAL, PRB, SUSPECT, THROUGHPUT, DetectorConfig
from oran_lab.ollama import AgentConfig, strict_json
from oran_lab.replay import ReplayConfig
from oran_lab.simulator import Limits
from oran_lab.ui_runs import (
    ARCHITECTURES, SOURCES, TERMINAL, RunConfig, active_run, available_indices, discover_models, list_runs,
    read_events, run_path, send_command, start_run, status,
)
from oran_lab.experiment import read_json

PAGES = ("Visão geral", "Configurar execução", "Monitoramento", "Inspeção do agente")
LABELS = {
    "iniciando": "Iniciando", "preparando": "Preparando", "executando": "Em execução", "pausada": "Pausada",
    "concluida": "Concluída", "interrompida": "Interrompida", "falha": "Falha", "iniciada": "Em andamento",
    "recusada": "Recusada", "dispensada": "Dispensada", NORMAL: "Normal", SUSPECT: "Suspeita",
    INSUFFICIENT: "Insuficiente",
}
COMPONENTS = {"replay": "Replay histórico", "detector": "Detector", "mcp": "Consultas MCP", "rag": "Recuperação RAG",
              "inferencia": "Inferência", "validacao": "Validação", "fallback": "Fallback",
              "execucao": "Execução simulada", "verificacao": "Verificação"}
ERRORS = (ValueError, OSError, ImportError, HTTPException)
STYLE = """
<style>
[data-testid="stAppViewContainer"] .block-container {max-width: 1420px; padding-top: 2.2rem; padding-bottom: 3rem}
[data-testid="stSidebar"] {border-right: 1px solid #26394A}
[data-testid="stAppDeployButton"] {display: none}
[data-testid="stMetric"] {border: 1px solid #2B4558; background: #122232; border-radius: 12px; padding: 13px 16px}
[data-testid="stMetricLabel"] {color: #BFD0DD}
h1,h2,h3 {letter-spacing: -0.025em}
@media (max-width:700px) {
  [data-testid="stHorizontalBlock"] {flex-wrap: wrap}
  [data-testid="stColumn"] {min-width: 180px; flex: 1 1 180px}
}
</style>
"""


def display(value, digits=2):
    return "—" if value is None else f"{value:.{digits}f}".replace(".", ",")


def route(page):
    st.session_state["pagina"] = page


def overview(workspace):
    st.title("O-RAN Agentic Lab")
    st.write("Configure uma execução, acompanhe janelas de KPM e inspecione as decisões do simulador.")
    runs = list_runs(workspace)
    current = active_run(workspace)
    recent = runs[0] if runs else None
    a, b, c = st.columns(3)
    a.metric("Execução operacional", "Ativa" if current else "Livre")
    b.metric("Execuções nesta interface", len(runs))
    c.metric("Último resultado", LABELS.get(status(run_path(workspace, recent["id"]))["estado"], "—") if recent else "—")
    st.subheader("Fluxo de trabalho")
    labels = ["Configurar execução", "Monitoramento", "Inspeção do agente"]
    descriptions = ["Escolha a origem dos KPMs, o modo de decisão e os limites operacionais.",
                    "Controle o avanço do replay e acompanhe detector, consultas e ações.",
                    "Confira entradas do modelo, propostas, referências e efeitos no simulador."]
    for col, label, detail in zip(st.columns(3), labels, descriptions, strict=True):
        with col, st.container(border=True):
            st.markdown(f"**{label}**")
            st.write(detail)
            st.button(f"Abrir {label.lower()}", on_click=route, args=(label,), width="stretch")
    st.caption("O Excel oficial contém dados históricos. Os cenários sintéticos são identificados na seleção.")


@st.cache_data(ttl=8, show_spinner=False)
def model_choices():
    return discover_models()


def configure(workspace):
    st.title("Configurar execução")
    st.caption("Configuração exploratória. Os parâmetros são fixados no manifesto ao iniciar.")
    old = st.session_state.get("submitted_run")
    if old:
        st.success(f"Execução criada · {old[:8]}")
        monitor, new = st.columns(2)
        monitor.button("Abrir monitoramento", on_click=route, args=("Monitoramento",), width="stretch")
        if new.button("Preparar nova execução", width="stretch"):
            del st.session_state["submitted_run"]
            st.session_state.pop("request_id", None)
            st.rerun()
        return

    a, b = st.columns(2)
    architecture = a.selectbox("Arquitetura", ARCHITECTURES, format_func=lambda key: f"{key} · {ARCHITECTURES[key]}")
    source = b.selectbox("Fonte dos KPMs", SOURCES, format_func=SOURCES.get)
    model = index = None
    ready = True
    if architecture != "A":
        if st.button("Atualizar modelos locais"):
            model_choices.clear()
        try:
            tags, server = model_choices()
        except ERRORS as error:
            st.warning(str(error))
            tags, server = [], None
        model = st.selectbox("Modelo gerador local", tags, index=0 if tags else None)
        ready = bool(model)
        if server:
            st.caption(f"Ollama {server} · loopback")
        if not tags:
            st.info("Para B–E, o Ollama precisa oferecer um modelo local de geração já instalado.")
    if architecture in "CE":
        indices = available_indices(workspace)
        index = st.selectbox("Índice RAG local", indices, index=0 if indices else None)
        ready &= bool(index)
        if not indices:
            st.info("Prepare um índice compatível em data/rag com oran-rag indexar.")

    if "request_id" not in st.session_state:
        st.session_state["request_id"] = uuid4().hex
    default_size = 30 if source == "oficial" else 2 if source == "demonstracao" else 3
    with st.form(f"config-{source}-{architecture}"):
        st.subheader("Replay e detector")
        x, y = st.columns(2)
        size = x.number_input("Tamanho da janela (registros)", 1, 4096, default_size)
        stride = y.number_input("Avanço do replay (registros)", 1, 4096, default_size)
        x, y, z = st.columns(3)
        reference = x.number_input("Janelas de referência", 1, 100, 3)
        threshold = y.number_input("Queda mínima de throughput (%)", 1, 100, 30)
        persistence = z.number_input("Janelas de persistência", 1, 100, 2)
        x, y = st.columns(2)
        coverage = x.number_input("Cobertura mínima (%)", 1, 100, 80)
        prb = y.number_input("Tolerância de queda do PRB (%)", 0, 100, 10)
        with st.expander("Limites do simulador"):
            x, y, z = st.columns(3)
            history = x.number_input("Tamanho máximo do histórico", 1, 4096, 120)
            budget = y.number_input("Orçamento de registros adicionais", 0, 100000, 240)
            minimum = z.number_input("Avanço mínimo de inspeção", 1, 4096, 1)
        if architecture != "A":
            with st.expander("Inferência Ollama", expanded=True):
                x, y, z = st.columns(3)
                temperature = x.number_input("Temperatura", 0.0, 2.0, 0.0, 0.05)
                seed = y.number_input("Semente", -2147483648, 2147483647, 42)
                timeout = z.number_input("Timeout de inferência (s)", 1, 600, 90)
                x, y, z = st.columns(3)
                context = x.number_input("Contexto (tokens)", 512, 131072, 8192, 128)
                generation = y.number_input("Geração máxima (tokens)", 1, 8192, 512)
                calls = z.number_input("Orçamento de chamadas de chat", 1, 4096, 4)
                selection = st.selectbox("Janelas elegíveis", ("suspeitas", "todas"),
                                         format_func=lambda x: "Somente suspeitas" if x == "suspeitas" else "Todas")
        reads, mcp_timeout, top_k, min_score = None, 5, 2, 0.35
        if architecture in "DE":
            with st.expander("Consultas MCP"):
                x, y = st.columns(2)
                reads = x.number_input("Limite de consultas por janela", 1, 4, 1)
                mcp_timeout = y.number_input("Timeout MCP (s)", 1, 120, 5)
        if architecture in "CE":
            with st.expander("Recuperação RAG"):
                x, y = st.columns(2)
                top_k = x.number_input("Top-K", 1, 8, 2)
                min_score = y.number_input("Similaridade mínima", -1.0, 1.0, 0.35, 0.05)
        paused = st.checkbox("Iniciar em pausa")
        submitted = st.form_submit_button("Iniciar execução", type="primary", disabled=not ready)
    if submitted:
        try:
            agent = AgentConfig(model=model, seed=seed, num_ctx=context, num_predict=generation, timeout=timeout,
                                temperature=temperature, max_calls=calls, selection=selection) if model else None
            config = RunConfig(architecture, source, ReplayConfig(size, stride),
                               DetectorConfig(reference, threshold / 100, persistence, coverage / 100, prb / 100),
                               Limits(history, budget, minimum), agent, reads, mcp_timeout, index, top_k, min_score,
                               paused)
            st.session_state["submitted_run"] = start_run(config, workspace, request_id=st.session_state["request_id"])
        except ERRORS as error:
            st.error(str(error))
        else:
            st.rerun()


def choose_run(workspace, key):
    records = {item["id"]: item for item in list_runs(workspace)}
    if not records:
        st.info("Nenhuma execução registrada. Use Configurar execução para iniciar.")
        return None, None
    run_id = st.selectbox("Execução", records, key=key,
                          format_func=lambda k: f"{k[:8]} · {records[k]['configuracao']['architecture']} · "
                                                f"{SOURCES[records[k]['configuracao']['source']]}")
    return run_path(workspace, run_id), records[run_id]


def cached_events(directory):
    cache = st.session_state.setdefault("journal_cache", {})
    events = cache.setdefault(directory.name, [])
    events.extend(read_events(directory, after=events[-1]["seq"] if events else 0))
    return events


def chart(points, field, reference, threshold=None, *, revision):
    color = "#4CE4CF" if field == THROUGHPUT else "#79AFFF"
    fig = go.Figure(go.Scatter(x=list(points), y=[row.get(field) for row in points.values()],
                              mode="lines+markers", line={"color": color, "width": 2.5},
                              marker={"size": 5}, name=field, connectgaps=False))
    if reference is not None:
        fig.add_hline(y=reference, line_dash="dot", line_color="#B9C9D8", annotation_text="Referência")
    if threshold is not None:
        fig.add_hline(y=threshold, line_dash="dash", line_color="#FFB46E", annotation_text="Limiar")
    fig.update_layout(height=300, margin={"l": 38, "r": 18, "t": 16, "b": 43},
                      paper_bgcolor="#122232", plot_bgcolor="#122232", font={"color": "#D8E5EF"},
                      xaxis_title="Register", yaxis_title="Valor registrado", hovermode="x unified",
                      uirevision=revision)
    fig.update_xaxes(gridcolor="#263D51")
    fig.update_yaxes(gridcolor="#263D51")
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False}, key=field)


@st.fragment(run_every="1s")
def live_monitor(workspace):
    directory, manifest = choose_run(workspace, "monitor_run")
    if directory is None:
        return
    active = active_run(workspace) == manifest["id"]
    snapshot = status(directory)
    events = cached_events(directory)
    state = snapshot["estado"]
    st.caption(f"{SOURCES[manifest['configuracao']['source']]} · "
               f"{'execução operacional' if active else 'resultado gravado'} · ID {manifest['id'][:8]}")
    if active:
        mode = read_json(directory / "controle.json")["modo"]
        controls = (("Pausar", "pausar", mode == "pausar"), ("Continuar", "continuar", mode == "continuar"),
                    ("Avançar uma janela", "avancar", state != "pausada" or mode != "pausar"),
                    ("Interromper", "interromper", False))
        for col, (label, command, disabled) in zip(st.columns(4), controls, strict=True):
            if col.button(label, disabled=disabled or mode == "interromper", width="stretch"):
                try:
                    send_command(directory, command)
                    mode = command
                except ERRORS as error:
                    st.warning(str(error))
        if mode in ("pausar", "interromper") and state != "pausada":
            st.info("Solicitação registrada. A janela em andamento pode terminar antes do controle ser aplicado.")
    if snapshot.get("erro"):
        st.error(snapshot["erro"])
    started = [e for e in events if e["componente"] == "replay" and e["estado"] == "concluida"]
    detections = [e["dados"]["deteccao"] for e in events if e["componente"] == "detector" and e["estado"] == "concluida"]
    completed = [e for e in events if e["componente"] == "janela" and e["estado"] == "concluida"]
    total = next((e["dados"]["total_janelas"] for e in events
                  if e["componente"] == "preparacao" and e["estado"] == "concluida"), None)
    detection = detections[-1] if detections else None
    sim = completed[-1]["dados"]["estado_simulador"] if completed else None
    window = started[-1]["janela"] if started else None
    a, b, c, d = st.columns(4)
    a.metric("Estado", LABELS.get(state, state))
    b.metric("Janela atual", str(window) if window is not None else "—")
    c.metric("Detecção", LABELS[detection["situacao"]] if detection else "—")
    d.metric("Alertas registrados", len(sim["alertas"]) if sim is not None else "—")
    if total is not None:
        st.progress(len(completed) / total if total else 0, text=f"{len(completed)} de {total} janelas concluídas")

    points = {}
    for event in started:
        points.update({row["Register"]: row for row in event["dados"]["pontos"]})
    if points:
        ref = detection["referencia"]["medianas"] if detection else {}
        limit = ref[THROUGHPUT] * (1 - detection["parametros"]["throughput_drop"]) if ref.get(THROUGHPUT) is not None else None
        x, y = st.columns(2)
        with x:
            st.subheader("Throughput UL")
            chart(points, THROUGHPUT, ref.get(THROUGHPUT), limit, revision=manifest["id"])
        with y:
            st.subheader("PRB UL")
            chart(points, PRB, ref.get(PRB), revision=manifest["id"])
    if detection:
        x, y, z, w = st.columns(4)
        x.metric("Referência UL", display(ref.get(THROUGHPUT)))
        y.metric("Limiar UL", display(limit))
        z.metric("Cobertura UL", display(detection["metricas"][THROUGHPUT]["cobertura"] * 100, 0) + "%")
        w.metric("Cobertura PRB UL", display(detection["metricas"][PRB]["cobertura"] * 100, 0) + "%")
        st.caption(f"{detection['justificativa']} Cobertura mínima configurada "
                   f"{detection['parametros']['min_coverage']:.0%}.")
    st.subheader("Componentes da janela")
    scoped = [e for e in events if e["janela"] == window and e["componente"] in COMPONENTS]
    latest = {e["componente"]: e for e in scoped}
    totals = {key: sum(e["dados"]["tempo_s"] for e in scoped
                       if e["componente"] == key and "tempo_s" in e["dados"])
              for key in COMPONENTS if any(e["componente"] == key and "tempo_s" in e["dados"] for e in scoped)}
    components = pd.DataFrame([
        {"Componente": label, "Estado": LABELS.get(latest[key]["estado"], latest[key]["estado"])
         if key in latest else "—", "Tempo (s)": display(totals.get(key), 4)}
        for key, label in COMPONENTS.items()
    ])
    colors = {"Concluída": "#72E2CD", "Em andamento": "#9AC5FF", "Recusada": "#FFB76E", "Falha": "#FFA09F"}
    styled = components.style.map(lambda value: f"color:{colors[value]};font-weight:bold" if value in colors else "",
                                  subset=["Estado"])
    st.dataframe(styled, hide_index=True, width="stretch")
    if sim is not None:
        with st.expander("Alertas e eventos do simulador"):
            st.json({"alertas": sim["alertas"], "eventos": sim["eventos"]}, expanded=False)
    actions = [{"Janela": event["janela"], "Ação": (action["proposta"] or {}).get("acao"),
                "Origem": action["origem"], "Validação": action["validacao"]["estado"],
                "Execução": action["execucao"]["estado"], "Motivo": action["execucao"]["justificativa"]}
               for event in reversed(completed) for action in event["dados"]["historico"]]
    st.subheader("Histórico de ações")
    if actions:
        st.dataframe(actions, hide_index=True, width="stretch")
    else:
        st.caption("As ações aparecem quando a primeira janela encerra.")


def text_response(audit):
    raw = audit.get("resposta_modelo")
    if raw is None and audit.get("resposta_http"):
        try:
            body = strict_json(audit["resposta_http"])
            raw = body["message"]["content"]
        except (ValueError, TypeError, KeyError):
            return None
    return raw


@st.fragment(run_every="1s")
def inspect_run(workspace):
    directory, manifest = choose_run(workspace, "inspect_run")
    if directory is None:
        return
    st.caption(SOURCES[manifest["configuracao"]["source"]])
    finished = {e["janela"]: e["dados"] for e in cached_events(directory) if e["componente"] == "janela"}
    if not finished:
        st.info("A inspeção estará disponível após a primeira janela concluída.")
        return
    windows = sorted(finished, reverse=True)
    preferred = next((n for n in windows if (finished[n]["agente"] or {}).get("contexto") is not None), windows[0])
    number = st.selectbox("Janela concluída", windows, index=windows.index(preferred), key=f"janela-{directory.name}")
    item = finished[number]
    audit = item["agente"]
    if audit:
        evidence, proposal, investigated = st.tabs(["Evidência", "Proposta do modelo", "MCP e RAG"])
        with evidence:
            if audit["contexto"] is None:
                st.info(f"Inferência dispensada ({audit['dispensa']}).")
            else:
                st.json(audit.get("contexto_final", audit["contexto"]), expanded=2)
                st.caption("Evidências fornecidas ao modelo na janela autorizada.")
        with proposal:
            if audit.get("erro"):
                st.warning(audit["erro"])
            raw = text_response(audit)
            if raw:
                st.code(raw, language="json")
            if audit["proposta_modelo"]:
                st.json(audit["proposta_modelo"])
            st.caption("Justificativa declarada na resposta do modelo.")
        with investigated:
            if audit.get("mcp"):
                st.markdown("**Chamadas MCP**")
                st.json(audit["mcp"]["ferramentas"], expanded=2)
                if audit["mcp"].get("erro_acao"):
                    st.warning(audit["mcp"]["erro_acao"])
                with st.expander("Evidência e resposta da seleção MCP"):
                    for selection in audit.get("inferencias_consulta", []):
                        st.json(selection["contexto"], expanded=False)
                        raw = text_response(selection)
                        if raw:
                            st.code(raw, language="json")
            if audit.get("rag"):
                rag = audit["rag"]
                st.markdown("**Trechos apresentados ao modelo**")
                st.text(f"Recuperação: {rag['estado']}")
                hits = {hit["id"]: hit["texto"] for hit in rag["recuperados"]}
                for hit in rag["referencias_apresentadas"]:
                    pages = ", ".join(map(str, hit["paginas_pdf"]))
                    with st.expander(f"{hit['ref']} · {hit['documento']} V{hit['versao']} §{hit['secao']}"):
                        st.caption(f"Páginas PDF {pages} · cosseno {display(hit['score'], 3)}")
                        st.text(hits[hit["id"]])
                st.json({"ids_citados": rag.get("referencias_citadas"),
                         "validacao_estrutural": rag.get("referencias_validas")})
                st.caption("A conferência de IDs verifica a estrutura da resposta. O suporte técnico exige avaliação humana.")
            if not audit.get("mcp") and not audit.get("rag"):
                st.caption("Nenhuma consulta MCP ou RAG registrada para esta janela.")
        if audit["fallback"]:
            st.subheader("Fallback")
            st.json(audit["fallback"])
    else:
        st.caption("Decisão da política determinística Python.")

    st.subheader("Validação e efeito no simulador")
    for entry in item["historico"]:
        what = ("Ação executada" if entry["execucao"]["estado"] == "executada" else
                "Aceita sem alteração" if entry["validacao"]["estado"] == "aceita"
                and entry["execucao"]["estado"] == "nao_executada" else
                "Proposta recusada" if entry["validacao"]["estado"] == "recusada" else "Falha de execução")
        with st.expander(f"{what} · {entry['origem']}", expanded=True):
            st.json({k: entry[k] for k in ("proposta", "validacao", "execucao", "verificacao")}, expanded=2)
            a, b = st.columns(2)
            a.markdown("**Estado anterior**")
            a.json(entry["estado_anterior"], expanded=False)
            b.markdown("**Estado posterior**")
            b.json(entry["estado_posterior"], expanded=False)


def main():
    st.set_page_config(page_title="O-RAN Agentic Lab", layout="wide", initial_sidebar_state="expanded")
    st.html(STYLE)
    with st.sidebar:
        st.markdown("## O-RAN Agentic Lab")
        st.caption("Replay de KPMs · Simulador")
        page = st.radio("Navegação", PAGES, key="pagina", label_visibility="collapsed")
    workspace = Path.cwd()
    if page == "Visão geral":
        overview(workspace)
    elif page == "Configurar execução":
        configure(workspace)
    elif page == "Monitoramento":
        st.title("Monitoramento")
        live_monitor(workspace)
    else:
        st.title("Inspeção do agente")
        inspect_run(workspace)


if __name__ == "__main__":
    main()
