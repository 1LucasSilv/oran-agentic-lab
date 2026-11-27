"""Páginas Streamlit da Etapa 7.1.1."""

from http.client import HTTPException
from pathlib import Path
from uuid import uuid4
from dataclasses import replace

import plotly.graph_objects as go
import pandas as pd
import streamlit as st

from oran_lab.detector import INSUFFICIENT, NORMAL, PRB, SUSPECT, THROUGHPUT
from oran_lab.ollama import strict_json
from oran_lab.replay import ReplayConfig
from oran_lab.ui_runs import (
    ARCHITECTURES, SOURCES, TERMINAL, RunConfig, active_run, available_indices, list_runs,
    read_events, run_path, send_command, start_run, status, worker_alive, active_experiment,
)
from oran_lab.experiment import read_json

from oran_lab.ui_pages import (
    choose, config_fields, datasets_page, embedding_tags, experiments_page, generator_tags, hardware_details,
    initial_preset, knowledge_page, local_inventory, models_page, presets_page, reference_card, refresh_inventory,
    source_choices,
)
from oran_lab.ui_resources import inspect_index, save_preset

NAVIGATION = {
    "Laboratório": (("⌂", "Visão geral"), ("⚙", "Configurar execução"), ("◫", "Monitoramento"),
                    ("◎", "Inspeção do agente")),
    "Pesquisa": (("◈", "Experimentos"),),
    "Recursos": (("✦", "Modelos de IA"), ("▤", "Datasets"), ("▥", "Base de conhecimento"),
                 ("◇", "Cenários e presets")),
}
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


def source_name(manifest):
    key = manifest["configuracao"]["source"]
    metadata = manifest.get("recursos", {}).get("fonte", {})
    kind = "Sintético" if metadata.get("tipo") == "sintetico" else "Importado"
    return SOURCES.get(key, f"{kind} · {metadata.get('nome', key)}")


def overview(workspace):
    st.title("O-RAN Agentic Lab")
    st.write("Replay de KPMs, investigação com MCP e RAG e decisão em simulador.")
    hardware_details()
    st.button("Verificar ambiente novamente", on_click=refresh_inventory)
    version, models, error = local_inventory()
    current = active_run(workspace) or active_experiment(workspace)
    runs = list_runs(workspace)
    compatible = 0
    installed_embeddings = {row["tag"]: row["digest"] for row in models if row["tag"] in embedding_tags(models)}
    for name in available_indices(workspace):
        try:
            meta = inspect_index(workspace, name)["metadados"]
            compatible += int(bool(installed_embeddings.get(meta["modelo"])) and
                              installed_embeddings[meta["modelo"]] == meta["digest"])
        except (OSError, ValueError, KeyError):
            continue
    a, b, c, d = st.columns(4)
    a.metric("Ollama local", version or "Indisponível")
    b.metric("Geradores locais", len(generator_tags(models)) if version else "—")
    c.metric("Índices RAG compatíveis", compatible if version else "—")
    d.metric("Worker local", "Em atividade" if current or worker_alive(workspace) else "Livre")
    if error:
        st.caption(error)
    st.subheader("Fluxo do laboratório")
    for col, title, detail in zip(st.columns(4), ("Dados", "Detector", "Decisão", "Simulador"),
                                  ("Registros por janela", "Heurísticas de UL", "Python ou modelo local",
                                   "Validação e verificação"), strict=True):
        with col, st.container(border=True):
            st.markdown(f"**{title}**")
            st.caption(detail)
    st.subheader("Acesso rápido")
    for col, target in zip(st.columns(3), ("Configurar execução", "Experimentos", "Datasets"), strict=True):
        col.button(target, on_click=route, args=(target,), width="stretch", key=f"shortcut-{target}")
    st.subheader("Execuções operacionais recentes")
    if runs:
        st.dataframe([{"ID": row["id"][:12], "Início (UTC)": row["inicio_utc"][:19],
                       "Fonte": source_name(row), "Arquitetura": row["configuracao"]["architecture"],
                       "Estado": LABELS.get(status(run_path(workspace, row["id"]))["estado"], "—")}
                      for row in runs[:5]], hide_index=True, width="stretch")
    else:
        st.caption("Nenhuma execução operacional registrada.")


def configure(workspace):
    st.title("Configurar execução")
    st.caption("Os parâmetros e recursos são fixados no manifesto ao iniciar.")
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

    draft = st.session_state.get("preset_config")
    preferred = st.session_state.get("modelo_preferido")
    revision = st.session_state.get("preset_revision", 0)
    a, b = st.columns(2)
    architecture = a.selectbox("Arquitetura", ARCHITECTURES,
                               index=choose(ARCHITECTURES, draft.architecture if draft else "B" if preferred else "A"),
                               format_func=lambda key: f"{key} · {ARCHITECTURES[key]}", key=f"arch-{revision}")
    sources = source_choices(workspace)
    source = b.selectbox("Fonte dos KPMs", sources, index=choose(sources, draft.source if draft else None),
                         format_func=sources.get, key=f"source-{revision}")
    model = index = None
    ready = True
    if architecture != "A":
        st.button("Atualizar modelos locais", on_click=refresh_inventory)
        rows = local_inventory()
        if rows[2]:
            st.warning(rows[2])
        tags = generator_tags(rows[1])
        model = st.selectbox("Modelo gerador local", tags,
                             index=choose(tags, draft.agent.model if draft and draft.agent else preferred),
                             key=f"model-{revision}")
        ready = bool(model)
    if architecture in "CE":
        indices = available_indices(workspace)
        index = st.selectbox("Índice RAG local", indices, index=choose(indices, draft.index if draft else "indice.json"),
                             key=f"index-{revision}")
        ready &= bool(index)
        if not indices:
            st.info("Use Base de conhecimento para preparar um índice compatível.")

    if "request_id" not in st.session_state:
        st.session_state["request_id"] = uuid4().hex
    size = 30 if source == "oficial" else 2 if source == "demonstracao" else 3
    defaults = draft or replace(initial_preset(architecture), replay=ReplayConfig(size))
    with st.form(f"config-{source}-{architecture}-{revision}"):
        factory = config_fields(architecture, source, model, index, defaults)
        with st.expander("Salvar como preset"):
            preset_name = st.text_input("Nome do preset", max_chars=100)
            save = st.form_submit_button("Salvar configuração", disabled=not ready)
        submitted = st.form_submit_button("Iniciar execução", type="primary", disabled=not ready)
    if save or submitted:
        try:
            config = factory()
            if save:
                row = save_preset(workspace, preset_name, config)
                st.success(f"Preset salvo · {row['id']}")
            else:
                st.session_state["submitted_run"] = start_run(config, workspace, request_id=st.session_state["request_id"])
                st.rerun()
        except ERRORS as error:
            st.error(str(error))


def choose_run(workspace, key):
    records = {item["id"]: item for item in list_runs(workspace)}
    if not records:
        st.info("Nenhuma execução registrada. Use Configurar execução para iniciar.")
        return None, None
    run_id = st.selectbox("Execução", records, key=key,
                          format_func=lambda k: f"{k[:8]} · {records[k]['configuracao']['architecture']} · "
                                                f"{source_name(records[k])}")
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
    st.caption(f"{source_name(manifest)} · "
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
    window = started[-1]["janela"] if started else None
    detection = next((d for d in reversed(detections) if d["janela"]["id"] == window), None)
    sim = completed[-1]["dados"]["estado_simulador"] if completed else None
    a, b, c, d = st.columns(4)
    a.metric("Estado", LABELS.get(state, state))
    b.metric("Janela atual", str(window) if window is not None else "—")
    c.metric("Detecção", LABELS[detection["situacao"]] if detection else "—")
    d.metric("Alertas registrados", len(sim["alertas"]) if sim is not None else "—",
             help=f"Estado após a janela concluída {completed[-1]['janela']}." if completed else "Aguardando a primeira janela.")
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
    arch = manifest["configuracao"]["architecture"]
    disabled = ({"inferencia", "fallback"} if arch == "A" else set())
    if arch not in "DE":
        disabled.add("mcp")
    if arch not in "CE":
        disabled.add("rag")
    window_complete = any(item["janela"] == window for item in completed)
    components = pd.DataFrame([
        {"Componente": label, "Estado": LABELS.get(latest[key]["estado"], latest[key]["estado"])
         if key in latest else ("Desabilitado" if key in disabled else "Dispensado" if window_complete else "Aguardando"), "Tempo (s)": display(totals.get(key), 4)}
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
    st.caption(source_name(manifest))
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
                proposal = audit["proposta_modelo"]
                st.markdown(f"**{proposal['acao'].replace('_', ' ').capitalize()}**")
                st.write(proposal["justificativa"])
                st.json(proposal["parametros"], expanded=False)
            st.caption("Justificativa declarada na resposta do modelo.")
        with investigated:
            if audit.get("mcp"):
                st.markdown("**Chamadas MCP**")
                calls = audit["mcp"]["ferramentas"]
                if calls:
                    st.dataframe([{"Ferramenta": row["nome"] or "Seleção",
                                   "Estado": "Com resultado" if row.get("resultado") is not None else row.get("erro") or "Sem resultado",
                                   "Tempo (s)": display(row.get("tempo_s"), 4)} for row in calls], hide_index=True)
                else:
                    st.caption("Nenhuma ferramenta foi chamada.")
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
                    reference_card(hit, hits[hit["id"]])
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

    with st.expander("Auditoria avançada da janela"):
        st.json(item, expanded=False)
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
    workspace = Path.cwd()
    page = st.session_state.setdefault("pagina", "Visão geral")
    with st.sidebar:
        st.markdown("## O-RAN Agentic Lab")
        st.caption("Replay de KPMs · Simulador")
        for name, entries in NAVIGATION.items():
            with st.expander(name, expanded=any(target == page for _, target in entries)):
                for icon, target in entries:
                    st.button(f"{icon}  {target}", type="primary" if page == target else "secondary",
                              key=f"nav-{target}", on_click=route, args=(target,), width="stretch")
    pages = {"Visão geral": overview, "Configurar execução": configure, "Experimentos": experiments_page,
             "Modelos de IA": models_page, "Datasets": datasets_page, "Base de conhecimento": knowledge_page,
             "Cenários e presets": presets_page}
    if page in pages:
        pages[page](workspace)
    else:
        st.title(page)
        (live_monitor if page == "Monitoramento" else inspect_run)(workspace)


if __name__ == "__main__":
    main()
