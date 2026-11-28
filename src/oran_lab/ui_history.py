"""Seletores e histórico de execuções na interface local."""

from collections import Counter

import streamlit as st

from .ui_records import recordings, save_identity
from .ui_runs import active_experiment, active_run

TARGETS = {"Monitoramento": "monitor_run", "Inspeção do agente": "inspect_run",
           "Central de execução": "central", "Resultados": "results", "Modo apresentação": "presentation"}


def open_record(page, record):
    st.session_state["pagina"] = page
    st.session_state[f"draft/{TARGETS[page]}"] = record.identity


def active_identity(workspace, entries):
    for kind, lookup in (("Operacional", active_run), ("Configurável", active_experiment)):
        if not any(record.kind == kind for record in entries.values()):
            continue
        try:
            run_id = lookup(workspace)
        except (ValueError, OSError):
            continue
        if run_id and (identity := f"{kind}/{run_id}") in entries:
            return identity
    return None


def default_identity(entries, preferred=None, active=None):
    return next((key for key in (preferred, active) if key in entries), next(iter(entries), None))


def selector_labels(entries, *, blind=False):
    labels = {key: record.legacy_title if blind else record.selector_label for key, record in entries.items()}
    duplicates = Counter(labels.values())
    for key, value in tuple(labels.items()):
        if duplicates[value] > 1:
            labels[key] = f"{value} · {entries[key].key[:12]}"
    collisions = Counter(labels.values())
    return {key: value if collisions[value] == 1 else f"{value} · {key}" for key, value in labels.items()}


def filter_history(entries, query="", *, dates=(), source=None, model=None, arch=None, kind=None, state=None):
    query = query.strip().casefold()
    output = {}
    for key, record in entries.items():
        if query and query not in record.title.casefold():
            continue
        if dates:
            stamp = record.started.astimezone().date() if record.started else None
            if stamp is None or not dates[0] <= stamp <= dates[-1]:
                continue
        if ((source and source not in record.sources) or (model and model not in record.models)
                or (arch and arch not in record.architectures) or (kind and record.kind != kind)
                or (state and record.state_label != state)):
            continue
        output[key] = record
    return output


def filter_widgets(entries, key):
    records = tuple(entries.values())
    with st.expander("Pesquisar e filtrar histórico"):
        a, b = st.columns(2)
        query = a.text_input("Pesquisar por nome", key=f"draft/{key}/query")
        dates = b.date_input("Intervalo de início · horário local", value=(), key=f"draft/{key}/dates")
        widgets = st.columns(3) + st.columns(2)
        fields = {"source": ("Cenário ou dataset", {source for record in records for source in record.sources}),
                  "model": ("Modelo", {model for record in records for model in record.models}),
                  "arch": ("Arquitetura", {arch for record in records for arch in record.architectures}),
                  "kind": ("Tipo de execução", {record.kind for record in records}),
                  "state": ("Estado", {record.state_label for record in records})}
        selections = {}
        for container, (field, (name, options)) in zip(widgets, fields.items(), strict=True):
            selections[field] = container.selectbox(name, sorted(options), index=None, placeholder="Todos",
                                                     key=f"draft/{key}/{field}")
    return filter_history(entries, query, dates=dates, **selections)


def select_record(workspace, key, predicate=lambda _: True, *, kinds=None, label="Execução", blind=False,
                  filters=True, entries=None):
    if entries is None:
        entries = recordings(workspace, kinds)
    entries = {identity: record for identity, record in entries.items() if predicate(record)}
    if entries and filters and not blind:
        entries = filter_widgets(entries, key)
    if not entries:
        st.info("Nenhum registro disponível para esta seleção.")
        return None
    labels = selector_labels(entries, blind=blind)
    chosen, widget = f"draft/{key}", f"pick/{key}"
    previous = st.session_state.get(chosen)
    preferred = default_identity(entries, previous, None if previous in entries else active_identity(workspace, entries))
    if st.session_state.get(widget) != preferred:
        st.session_state[widget] = preferred

    def remember():
        st.session_state[chosen] = st.session_state[widget]

    selected = st.selectbox(label, entries, format_func=labels.get, key=widget, on_change=remember)
    return entries[selected]


def edit_identity(workspace, record):
    with st.expander("Editar nome e descrição"):
        with st.form(f"identificacao-{record.identity}"):
            name = st.text_input("Nome visual", value=record.name, placeholder=record.automatic_name, max_chars=100)
            description = st.text_area("Descrição", value=record.description, max_chars=2000)
            if st.form_submit_button("Salvar identificação"):
                try:
                    save_identity(workspace, record, name, description)
                except (ValueError, OSError) as error:
                    st.error(str(error))
                else:
                    st.session_state["history_saved"] = record.identity
                    st.rerun()


def recent_history(workspace):
    st.subheader("Execuções recentes")
    st.caption("Horários locais · registros mais recentes primeiro")
    entries = recordings(workspace)
    if not entries:
        st.caption("Nenhuma execução registrada.")
        return
    visible = filter_widgets(entries, "history")
    if not visible:
        st.info("Nenhum registro corresponde aos filtros.")
        return
    per_page = 5
    pages = (len(visible) + per_page - 1) // per_page
    page = st.number_input("Página do histórico", 1, pages, step=1) if pages > 1 else 1
    offset = (page - 1) * per_page
    for record in list(visible.values())[offset:offset + per_page]:
        with st.container(border=True):
            a, b = st.columns([4, 1])
            a.text(record.title)
            b.caption(record.state_label)
            context = " · ".join(item for item in (record.context, record.local_start) if item)
            if context:
                st.caption(context)
            if record.description:
                st.text(record.description)
            if st.session_state.get("history_saved") == record.identity:
                st.success("Identificação salva.")
                st.session_state.pop("history_saved")
            pages_for_record = (["Monitoramento"] if record.kind == "Operacional" else
                                ["Central de execução"] if record.kind == "Configurável" else [])
            pages_for_record.extend(("Resultados", "Modo apresentação"))
            for col, target in zip(st.columns(len(pages_for_record)), pages_for_record, strict=True):
                col.button(target, key=f"history-{record.identity}-{target}", on_click=open_record,
                           args=(target, record), width="stretch")
            edit_identity(workspace, record)
