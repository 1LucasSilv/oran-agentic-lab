"""Componentes e páginas de gerenciamento de recursos da interface local."""

import json
import platform
import shutil
from dataclasses import asdict, replace
from http.client import HTTPException
from uuid import uuid4

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from openpyxl.utils.exceptions import InvalidFileException

from oran_lab.detector import DetectorConfig, PRB, THROUGHPUT
from oran_lab.data import OFFICIAL_SHA256
from oran_lab.dataset import OFFICIAL_PATH, dataset_digest
from oran_lab.experiment import read_json
from oran_lab.hardware import physical_memory, processor_name
from oran_lab.ollama import AgentConfig
from oran_lab.rag import Embedder, model_tag
from oran_lab.replay import ReplayConfig
from oran_lab.simulator import Limits, NO_ACTION, REGISTER_ALERT
from oran_lab.ui_experiments import (
    Comparison, experiment_path, interruption_requested, list_experiments, plan_comparison, request_interruption,
    start_comparison,
)
from oran_lab.ui_resources import (
    FIELDS, PRESET_ID, SOURCE_ID, audit_dataset, corpus_status, create_index, delete_model, import_dataset,
    inspect_index, inventory, list_resources, load_preset, pull_model, query_index, save_preset, save_scenario,
    import_preset, local_path,
    synthetic_frame, upload_frames,
)
from oran_lab.ui_runs import ARCHITECTURES, SOURCES, RunConfig, TERMINAL, active_experiment, available_indices, status

ERRORS = (ValueError, OSError, ImportError, HTTPException, InvalidFileException, KeyError, TypeError)


def gib(value):
    return f"{value / (1024**3):.2f} GiB" if value is not None else "Indisponível"


def source_choices(workspace):
    builtins = dict(SOURCES)
    try:
        path = local_path(workspace, OFFICIAL_PATH)
        stat = path.stat()
        if not official_identity(path, stat.st_size, stat.st_mtime_ns):
            builtins.pop("oficial")
    except (OSError, ValueError):
        builtins.pop("oficial")
    return {**builtins, **{key: f"{'Sintético' if row['tipo'] == 'sintetico' else 'Importado'} · {row['nome']}"
                            for key, row in list_resources(workspace, "fontes", SOURCE_ID).items()}}


@st.cache_data(ttl=30, show_spinner=False)
def official_identity(path, size, mtime_ns):
    return dataset_digest(path) == OFFICIAL_SHA256


@st.cache_data(ttl=12, show_spinner=False)
def local_inventory():
    try:
        version, rows = inventory()
        return version, rows, None
    except ERRORS as error:
        return None, [], str(error)


def refresh_inventory():
    local_inventory.clear()


def choose(options, value):
    keys = list(options)
    return keys.index(value) if value in keys else (0 if keys else None)


def generator_tags(rows):
    return sorted(row["tag"] for row in rows if "completion" in (row["capacidades"] or ()))


def embedding_tags(rows):
    return sorted(row["tag"] for row in rows if "embedding" in (row["capacidades"] or ()))


def hardware_details():
    st.caption(f"{platform.system()} · Python {platform.python_version()} · {platform.machine()} · "
               f"{processor_name() or 'CPU não declarada'} · RAM física {gib(physical_memory())}")


def config_fields(architecture, source, model, index, defaults, *, key, experimental=False):
    """Campos comuns aos fluxos operacional e experimental."""
    st.subheader("Replay e detector")
    x, y = st.columns(2)
    size = x.number_input("Tamanho da janela (registros)", 1, 4096, defaults.replay.size,
                          help="Número máximo de registros consecutivos por janela.", key=f"{key}/size")
    stride = y.number_input("Avanço do replay (registros)", 1, 4096, defaults.replay.advance,
                            help="Distância entre janelas. Lacunas de Register iniciam outro segmento.", key=f"{key}/stride")
    partial = st.checkbox("Incluir janelas incompletas", value=defaults.replay.include_partial, key=f"{key}/partial")
    x, y, z = st.columns(3)
    reference = x.number_input("Janelas de referência", 1, 100, defaults.detector.reference_windows,
                               help="Quantidade de janelas anteriores usada na linha de base.", key=f"{key}/reference")
    threshold = y.number_input("Queda mínima de throughput (%)", 0.01, 100.0, defaults.detector.throughput_drop * 100, key=f"{key}/threshold")
    persistence = z.number_input("Janelas de persistência", 1, 100, defaults.detector.persistence, key=f"{key}/persistence")
    x, y = st.columns(2)
    coverage = x.number_input("Cobertura mínima (%)", 0.01, 100.0, defaults.detector.min_coverage * 100,
                              help="Fração de amostras válidas exigida para cada métrica.", key=f"{key}/coverage")
    prb = y.number_input("Tolerância de queda do PRB (%)", 0.0, 100.0, defaults.detector.prb_tolerance * 100, key=f"{key}/prb")
    with st.expander("Limites do simulador"):
        x, y, z = st.columns(3)
        history = x.number_input("Tamanho máximo do histórico", 1, 4096, defaults.limits.max_history_size, key=f"{key}/history")
        budget = y.number_input("Orçamento de registros adicionais", 0, 100000, defaults.limits.history_budget, key=f"{key}/budget")
        minimum = z.number_input("Avanço mínimo de inspeção", 1, 4096, defaults.limits.min_inspection_stride, key=f"{key}/minimum")
    agent = defaults.agent or AgentConfig(num_ctx=8192, num_predict=512)
    if architecture != "A":
        with st.expander("Inferência Ollama", expanded=True):
            x, y, z = st.columns(3)
            temperature = x.number_input("Temperatura", 0.0, 2.0, float(agent.temperature), 0.05, key=f"{key}/temperature")
            seed = agent.seed if experimental else y.number_input("Semente operacional", -2147483648, 2147483647, agent.seed, key=f"{key}/seed")
            timeout = z.number_input("Timeout de inferência (s)", 1.0, 600.0, float(agent.timeout), key=f"{key}/timeout")
            x, y, z = st.columns(3)
            context = x.number_input("Contexto (tokens)", 512, 131072, agent.num_ctx, 128,
                                     help="Inclui evidências, instruções, schema e espaço reservado para geração.", key=f"{key}/context")
            generation = y.number_input("Geração máxima (tokens)", 1, 8192, agent.num_predict, key=f"{key}/generation")
            calls, failures, selection = agent.max_calls, agent.max_failures, "todas"
            if not experimental:
                calls = z.number_input("Orçamento operacional de chat", 0, 4096, agent.max_calls, key=f"{key}/calls")
                failures = st.number_input("Falhas consecutivas antes de fallback preventivo", 1, 4096, agent.max_failures, key=f"{key}/failures")
                selection = st.selectbox("Janelas elegíveis", ("suspeitas", "todas"), index=int(agent.selection == "todas"),
                                         format_func=lambda x: "Somente suspeitas" if x == "suspeitas" else "Todas", key=f"{key}/selection")
    reads, mcp_timeout, top_k, min_score = None, 5, 2, 0.35
    if architecture in "DE":
        with st.expander("Consultas MCP"):
            x, y = st.columns(2)
            reads = x.number_input("Limite de consultas por janela", 1, 4, defaults.mcp_reads or 1, key=f"{key}/reads")
            mcp_timeout = y.number_input("Timeout MCP (s)", 0.1, 120.0, float(defaults.mcp_timeout), key=f"{key}/mcp_timeout")
    if architecture in "CE":
        with st.expander("Recuperação RAG"):
            x, y = st.columns(2)
            top_k = x.number_input("Top-K", 1, 8, defaults.top_k, key=f"{key}/top_k")
            min_score = y.number_input("Similaridade mínima", -1.0, 1.0, float(defaults.min_score), 0.05, key=f"{key}/min_score")
    paused = False if experimental else st.checkbox("Iniciar em pausa", value=defaults.start_paused, key=f"{key}/paused")

    def build():
        options = AgentConfig(model=model, url=agent.url, seed=seed, num_ctx=context, num_predict=generation,
                              timeout=timeout, temperature=temperature, max_calls=calls, max_failures=failures,
                              selection=selection) if architecture != "A" else None
        return RunConfig(architecture, source, ReplayConfig(size, stride, partial),
                         DetectorConfig(reference, threshold / 100, persistence, coverage / 100, prb / 100),
                         Limits(history, budget, minimum), options, reads, mcp_timeout, index, top_k, min_score, paused)
    return build


def models_page(workspace):
    st.title("Modelos de IA")
    hardware_details()
    st.button("Atualizar inventário", on_click=refresh_inventory)
    version, rows, error = local_inventory()
    if error:
        st.warning(error)
        return
    st.caption(f"Ollama {version} · {len(rows)} tags locais · Disco livre no volume do laboratório {gib(shutil.disk_usage(workspace).free)}")
    st.dataframe([{"Modelo": row["tag"], "Arquitetura": row["arquitetura"], "Parâmetros": str(row["parametros"] or "—"),
                   "Quantização": row["quantizacao"], "Disco": gib(row["disco_bytes"]),
                   "Capacidades": ", ".join(row["capacidades"] or ()) or "Indisponível",
                   "Residente": row["residente"], "Memória reportada": gib(row["residencia_bytes"]),
                   "VRAM reportada": gib(row["vram_reportada_bytes"]), "Digest": row["digest"]} for row in rows],
                 hide_index=True, width="stretch")
    st.caption("Memória reportada pelo Ollama para modelos carregados. A RAM exclusiva e o espaço físico liberado por camadas compartilhadas podem estar indisponíveis.")
    generators = generator_tags(rows)
    selected = st.selectbox("Gerador para novas execuções", generators, index=0 if generators else None)
    if st.button("Usar gerador", disabled=not selected):
        st.session_state["modelo_preferido"] = selected
        draft = st.session_state.get("preset_config") or initial_preset("B")
        if draft.architecture == "A":
            draft = replace(draft, architecture="B", agent=initial_preset("B").agent)
        set_draft(replace(draft, agent=replace(draft.agent, model=selected)))
        st.rerun()
    download, remove = st.tabs(["Baixar modelo", "Remover modelo"])
    with download:
        with st.form("pull"):
            tag = st.text_input("Tag local a baixar", placeholder="nome:versão", max_chars=192)
            confirmed = st.checkbox("Autorizo o download pelo Ollama. O tamanho pode ser informado durante a transferência.")
            if st.form_submit_button("Baixar"):
                progress = st.progress(0, text="Aguardando o Ollama")

                def update(event):
                    total, completed = event.get("total"), event.get("completed")
                    fraction = min(1.0, completed / total) if total and completed is not None else 0
                    detail = f" · {gib(completed)} / {gib(total)} na camada" if total and completed is not None else ""
                    progress.progress(fraction, text=f"{event.get('status', 'Em andamento')}{detail}")

                try:
                    pull_model(workspace, tag, confirmed=confirmed, progress=update)
                    refresh_inventory()
                    progress.progress(1.0, text="Download concluído")
                except ERRORS as exc:
                    st.error(str(exc))
    with remove:
        with st.form("delete"):
            tag = st.selectbox("Tag instalada", [row["tag"] for row in rows])
            st.caption("A remoção pode impedir novos usos e liberar espaço. Modelos residentes ou referenciados são protegidos.")
            confirmation = st.text_input("Digite a tag exata para confirmar a remoção", max_chars=192)
            if st.form_submit_button("Remover modelo", disabled=not rows):
                try:
                    delete_model(workspace, tag, confirmed=confirmation == tag)
                    refresh_inventory()
                    st.success(f"Remoção confirmada pelo Ollama para {tag}.")
                except ERRORS as exc:
                    st.error(str(exc))


def datasets_page(workspace):
    from oran_lab.ui_runs import data_source

    st.title("Datasets")
    with st.container(border=True):
        st.markdown("**Excel oficial de KPMs históricos**")
        st.caption(str(OFFICIAL_PATH))
        if st.button("Verificar Excel oficial"):
            try:
                frame, metadata = data_source(RunConfig(source="oficial"), workspace)
                st.success(f"SHA-256 confirmado · {len(frame):,} registros")
                st.code(metadata["sha256"])
            except ERRORS as error:
                st.warning(str(error))
    st.subheader("Importar CSV ou XLSX")
    st.caption("Até 16 MiB e 100.000 registros. CSV UTF-8 com vírgula. Mapeie as métricas na escala de origem.")
    upload = st.file_uploader("Arquivo de origem", type=["csv", "xlsx"], max_upload_size=16)
    if upload:
        try:
            content = upload.getvalue()
            frame, sheets = upload_frames(upload.name, content)
            sheet = st.selectbox("Aba", sheets) if sheets else None
            if sheets and sheet != sheets[0]:
                frame, _ = upload_frames(upload.name, content, sheet)
            st.caption(f"{len(frame):,} registros · {len(frame.columns)} colunas")
            st.dataframe(frame.head(10), hide_index=True)
            fields = list(frame)
            mapping = {field: col.selectbox(field, fields, index=choose(fields, field), key=f"map-{field}")
                       for field, col in zip(FIELDS, st.columns(4), strict=True)}
            ues = sorted(frame[mapping["UE.Id"]].dropna().astype(str).str.strip().unique())
            ue = st.selectbox("UE para o replay", ues, index=0 if len(ues) == 1 else None)
            _, audit = audit_dataset(frame, mapping, ue)
            st.json(audit, expanded=False)
            name = st.text_input("Nome no catálogo", value=upload.name[:100], max_chars=100)
            if st.button("Salvar versão validada", type="primary"):
                saved = import_dataset(workspace, name, upload.name, content, mapping, sheet=sheet, ue=ue)
                st.success(f"Dataset preservado · {saved['id']}")
        except ERRORS as error:
            st.warning(str(error))
    st.subheader("Datasets importados")
    rows = [row for row in list_resources(workspace, "fontes", SOURCE_ID).values() if row["tipo"] == "dataset_importado"]
    if not rows:
        st.info("Nenhum dataset personalizado registrado.")
    for row in rows:
        with st.expander(f"{row['nome']} · {row['id'][-8:]}"):
            st.json({key: value for key, value in row.items() if key != "registros"}, expanded=2)


def knowledge_page(workspace):
    st.title("Base de conhecimento")
    st.caption("O corpus oficial sustenta consultas documentais. A indexação mantém os pesos do modelo.")
    _, documents = corpus_status(workspace)
    for document in documents:
        with st.expander(f"{document['especificacao']} · V{document['versao']}"):
            st.json(document, expanded=2)
    _, rows, error = local_inventory()
    tags = embedding_tags(rows)
    if error:
        st.warning(error)
    st.subheader("Índices locais")
    indices = available_indices(workspace)
    index = st.selectbox("Índice para verificar ou consultar", indices, index=0 if indices else None)
    if index:
        try:
            data = inspect_index(workspace, index)
            meta = data["metadados"]
            installed = next((row for row in rows if row["tag"] == model_tag(meta["modelo"])), None)
            compatible = bool(installed and installed["digest"] == meta["digest"] and installed["tag"] in tags)
            a, b, c = st.columns(3)
            a.metric("Fragmentos", meta["fragmentos"])
            b.metric("Dimensão", meta["dimensao"])
            c.metric("Tamanho", f"{data['tamanho_bytes'] / 1024:.1f} KiB")
            st.caption(f"Integridade verificada · {meta['modelo']} · " +
                       ("Embedding compatível" if compatible else "Compatibilidade do embedding não confirmada"))
            with st.expander("Proveniência e parâmetros do índice"):
                st.json({"sha256": data["sha256"], **meta}, expanded=False)
            with st.form("search"):
                query = st.text_input("Consulta documental de teste", max_chars=1500)
                a, b = st.columns(2)
                top = a.number_input("Top-K da consulta", 1, 8, 2)
                score = b.number_input("Cosseno mínimo", -1.0, 1.0, 0.35)
                if st.form_submit_button("Consultar índice", disabled=not compatible):
                    result = query_index(workspace, index, Embedder(AgentConfig(model=meta["modelo"])), query, top, score)
                    st.caption(f"{len(result['recuperados'])} resultados · {result['tempo_recuperacao_s']:.3f} s")
                    for hit in result["recuperados"]:
                        reference_card(hit, hit["texto"])
        except ERRORS as exc:
            st.warning(str(exc))
    with st.form("index"):
        st.subheader("Preparar índice")
        tag = st.selectbox("Modelo de embeddings instalado", tags, index=0 if tags else None)
        name = st.text_input("Nome do arquivo JSON", value="indice-personalizado.json", max_chars=69)
        confirmed = st.checkbox("Confirmo a indexação local dos PDFs oficiais verificados.")
        replace = st.checkbox("Autorizo substituir este nome se estiver livre de referências. A versão anterior será arquivada.")
        if st.form_submit_button("Construir índice", disabled=not tags):
            try:
                with st.spinner("Extraindo cláusulas e calculando embeddings"):
                    result = create_index(workspace, name, Embedder(AgentConfig(model=tag)), confirmed=confirmed, replace=replace)
                st.success(f"Índice gravado · {result['fragmentos']} fragmentos")
            except ERRORS as exc:
                st.error(str(exc))


def reference_card(hit, text):
    with st.container(border=True):
        reference = f"{hit['ref']} · " if hit.get("ref") else ""
        st.markdown(f"**{reference}{hit['documento']} V{hit['versao']} · § {hit['secao']}**")
        pages = ", ".join(map(str, hit["paginas_pdf"]))
        st.caption(f"Páginas PDF {pages} · Cosseno {hit['score']:.3f}")
        st.text(text)


def scenario_editor(workspace):
    st.caption("Cada linha descreve um segmento. Deixe uma métrica vazia para simular ausência de medição.")
    name = st.text_input("Nome do cenário", max_chars=100)
    description = st.text_area("Descrição", max_chars=1200)
    template = pd.DataFrame({"registros": [6, 3, 6], "throughput": [100.0, 55.0, 100.0],
                             "prb": [40.0, 40.0, 40.0], "lacuna": [0, 0, 0]})
    editor = st.data_editor(template, num_rows="dynamic", hide_index=True, width="stretch", key="segmentos",
                            column_config={
                                "registros": st.column_config.NumberColumn("Registros", min_value=1, max_value=4096, step=1),
                                "throughput": st.column_config.NumberColumn("Throughput UL", min_value=0.0),
                                "prb": st.column_config.NumberColumn("PRB UL", min_value=0.0),
                                "lacuna": st.column_config.NumberColumn("Lacuna de Register antes do segmento", min_value=0, step=1),
                            })
    segments = json.loads(editor.to_json(orient="records"))
    try:
        for segment in segments:
            for key in ("registros", "lacuna"):
                value = segment[key]
                if type(value) in (int, float) and float(value).is_integer():
                    segment[key] = int(value)
        frame = synthetic_frame(segments)
        fig = go.Figure()
        for field, color in ((THROUGHPUT, "#4CE4CF"), (PRB, "#79AFFF")):
            preview = frame[["Register", field]].copy()
            values = preview[field].astype(object).where(preview[field].notna(), None).tolist()
            x, y = [], []
            for register, value in zip(preview["Register"], values, strict=True):
                if x and register != x[-1] + 1:
                    x.append(register - 1)
                    y.append(None)
                x.append(register)
                y.append(value)
            fig.add_scatter(x=x, y=y, name=field, mode="lines+markers", line={"color": color}, connectgaps=False)
        fig.update_layout(xaxis_title="Register", yaxis_title="Valor sintético", height=275,
                          margin={"l": 30, "r": 20, "t": 10, "b": 30})
        st.plotly_chart(fig, width="stretch")
        with st.expander("Expectativas operacionais opcionais"):
            st.caption("Declare ações antes da execução. O ID depende do replay escolhido no experimento.")
            declarations = st.data_editor(pd.DataFrame({"janela": pd.Series(dtype=int), "acao": pd.Series(dtype=str)}),
                                          num_rows="dynamic", hide_index=True, key="expectativas",
                                          column_config={
                                              "janela": st.column_config.NumberColumn("Janela", min_value=1, step=1),
                                              "acao": st.column_config.SelectboxColumn("Ação", options=[NO_ACTION, REGISTER_ALERT]),
                                          })
        if st.button("Salvar versão sintética", type="primary"):
            expectations = {}
            for row in json.loads(declarations.to_json(orient="records")):
                window = row["janela"]
                if type(window) not in (float, int) or not float(window).is_integer() or int(window) in expectations:
                    raise ValueError("Preencha IDs inteiros e únicos para as expectativas.")
                expectations[int(window)] = row["acao"]
            saved = save_scenario(workspace, name, description, segments, expectations)
            st.success(f"Cenário sintético salvo · {saved['id']}")
    except ERRORS as error:
        st.warning(str(error))
    for row in list_resources(workspace, "fontes", SOURCE_ID).values():
        if row["tipo"] == "sintetico":
            with st.expander(f"{row['nome']} · {row['id'][-8:]}"):
                st.json({key: value for key, value in row.items() if key != "registros"}, expanded=False)


def set_draft(config):
    st.session_state["preset_config"] = config
    st.session_state["preset_revision"] = st.session_state.get("preset_revision", 0) + 1
    st.session_state.pop("request_id", None)
    st.session_state.pop("submitted_run", None)
    st.session_state["pagina"] = "Configurar execução"


def initial_preset(architecture):
    return RunConfig(architecture=architecture, agent=AgentConfig(num_ctx=8192, num_predict=512) if architecture != "A" else None,
                     mcp_reads=1 if architecture in "DE" else None, index="indice.json" if architecture in "CE" else None)


def presets_page(workspace):
    st.title("Cenários e presets")
    synthetic, presets = st.tabs(["Cenários sintéticos", "Presets"])
    with synthetic:
        scenario_editor(workspace)
    with presets:
        records = list_resources(workspace, "presets", PRESET_ID)
        defaults = {key: initial_preset(key) for key in ARCHITECTURES}
        keys = {**{key: f"{key} · {name}" for key, name in ARCHITECTURES.items()},
                **{key: record["nome"] for key, record in records.items()}}
        selection = st.selectbox("Preset", keys, format_func=keys.get)
        config = defaults[selection] if selection in defaults else RunConfig.from_dict(records[selection]["configuracao"])
        first, second = st.columns(2)
        if first.button("Carregar e revalidar", type="primary"):
            try:
                if selection in records:
                    config = load_preset(workspace, selection)
                else:
                    from oran_lab.ui_runs import prepare

                    prepare(config, workspace)
                set_draft(config)
                st.rerun()
            except ERRORS as error:
                st.error(str(error))
        second.download_button("Exportar configuração", json.dumps(asdict(config), ensure_ascii=False, indent=2),
                               file_name=f"preset-{selection}.json", mime="application/json")
        with st.expander("Configuração completa"):
            st.json(asdict(config), expanded=False)
        with st.form("duplicate"):
            name = st.text_input("Nome da cópia", max_chars=100)
            if st.form_submit_button("Duplicar preset"):
                try:
                    row = save_preset(workspace, name, config)
                    st.success(f"Preset salvo · {row['id']}")
                except ERRORS as error:
                    st.error(str(error))
        with st.form("import-preset"):
            upload = st.file_uploader("Configuração JSON exportada", type=["json"], max_upload_size=1)
            name = st.text_input("Nome do preset importado", max_chars=100)
            if st.form_submit_button("Importar e validar", disabled=upload is None):
                try:
                    row = import_preset(workspace, name, upload.getvalue())
                    st.success(f"Preset importado · {row['id']}")
                except ERRORS as error:
                    st.error(str(error))


@st.fragment(run_every="2s")
def experiment_status(workspace):
    with st.spinner("Consultando registros locais", show_time=False):
        active_experiment(workspace)
        records = {item["id"]: item for item in list_experiments(workspace)}
    identifier = st.selectbox("Experimento registrado", records, index=0 if records else None,
                              format_func=lambda k: f"{k[:12]} · {records[k]['inicio_utc'][:19]} UTC", key="draft/experiment_status")
    if identifier:
        directory = experiment_path(workspace, identifier)
        snapshot = status(directory)
        a, b, c = st.columns(3)
        a.metric("Estado", snapshot["estado"])
        b.metric("Sessões concluídas", snapshot.get("concluidas", 0))
        c.metric("Chamadas reservadas", sum(1 for _ in directory.glob("execucoes/*/chat/*-inicio.json")))
        if snapshot["estado"] not in TERMINAL:
            pending = interruption_requested(directory)
            if st.button("Interromper experimento", disabled=pending):
                try:
                    request_interruption(workspace, identifier)
                    pending = True
                except ERRORS as error:
                    st.warning(str(error))
            if pending:
                st.info("Interrupção solicitada. A janela atual pode terminar, incluindo uma chamada HTTP em curso.")
            else:
                st.caption("A interrupção é aplicada entre janelas ou sessões. Uma chamada HTTP em curso pode precisar terminar.")
        complete = snapshot.get("concluidas", 0) + snapshot.get("falhas", 0) + snapshot.get("interrompidas", 0)
        if snapshot.get("total"):
            st.progress(complete / snapshot["total"],
                        text=f"{complete}/{snapshot['total']} sessões registradas · {snapshot.get('falhas', 0)} falhas"
                             f" · {snapshot.get('interrompidas', 0)} interrompidas")
        if snapshot.get("erro"):
            st.error(snapshot["erro"])
        completed_files = list((directory / "execucoes").glob("*/resultado.json"))
        if completed_files:
            st.caption(f"{len(completed_files)} resultados brutos gravados")
            with st.expander("Sessões já registradas"):
                summaries = [(file.parent.name, read_json(file)) for file in sorted(completed_files)]
                st.dataframe([{"Sessão": job, "Estado": outcome["estado"], "Erro": outcome.get("erro")}
                              for job, outcome in summaries], hide_index=True)
        st.code(str(directory.relative_to(workspace)))
        with st.expander("Manifesto e configuração"):
            st.json(records[identifier], expanded=False)
            st.json(read_json(directory / "plano.json")["configuracao"], expanded=False)


def experiments_page(workspace):
    st.title("Experimentos")
    st.caption("Plano configurável com manifesto próprio. A bateria científica da Etapa 7 fica em results/etapa7.")
    experiment_status(workspace)
    st.subheader("Planejar comparação")
    sources = source_choices(workspace)
    selected_sources = st.multiselect("Fontes validadas", sources, default=["demonstracao"], format_func=sources.get,
                                      key="draft/exp/sources")
    treatments = st.multiselect("Arquiteturas", ARCHITECTURES, default=["A"],
                               format_func=lambda key: f"{key} · {ARCHITECTURES[key]}", key="draft/exp/architectures")
    index = model = None
    assignments = []
    llm_architectures = [arch for arch in treatments if arch != "A"]
    ready = bool(selected_sources and treatments)
    if llm_architectures:
        _, rows, error = local_inventory()
        tags = generator_tags(rows)
        default = choose(tags, st.session_state.get("modelo_preferido"))
        design = st.radio("Geradores", ("Modelo comum", "Modelos por arquitetura"), horizontal=True, key="draft/exp/design")
        if design == "Modelo comum":
            model = st.selectbox("Modelo comum B–E", tags, index=default, key="draft/exp/model")
            ready &= bool(model)
        else:
            for arch in llm_architectures:
                selected = st.multiselect(f"Geradores para {arch} · {ARCHITECTURES[arch]}", tags,
                                          default=[tags[default]] if default is not None else [],
                                          key=f"draft/exp/models-{arch}")
                assignments.extend((arch, tag) for tag in selected)
                ready &= bool(selected)
            model = assignments[0][1] if assignments else None
        if error:
            st.warning(error)
    rag = bool(set(treatments) & set("CE"))
    mcp = bool(set(treatments) & set("DE"))
    if rag:
        indices = available_indices(workspace)
        index = st.selectbox("Índice comum C e E", indices, index=0 if indices else None, key="draft/exp/index")
        ready &= bool(index)
    mode = "E" if rag and mcp else "C" if rag else "D" if mcp else "B" if llm_architectures else "A"
    decision_mode = st.radio("Regime", ("controlada", "ciclo_completo"), horizontal=True, key="draft/exp/mode",
                             format_func=lambda key: "Decisão controlada" if key == "controlada" else "Ciclo completo")
    purpose = st.radio("Finalidade", ("comparacao", "exploracao"), horizontal=True, key="draft/exp/purpose",
                       format_func=lambda key: "Comparação com variáveis fixas" if key == "comparacao" else "Exploração livre")
    a, b, c, d = st.columns(4)
    seeds = a.text_input("Sementes separadas por vírgula", "42", max_chars=160, key="draft/exp/seeds")
    repetitions = b.number_input("Repetições por semente", 1, 20, 1, key="draft/exp/repetitions")
    cap = c.number_input("Teto global de chat", 0, 2000, 12, key="draft/exp/cap")
    target = d.number_input("Janela-alvo (decisão controlada)", 1, 100000, 5, key="draft/exp/target")
    st.caption("MCP pode usar uma chamada de seleção adicional por janela. Inferência, replay e limites usam parâmetros comuns.")
    factory = config_fields(mode, selected_sources[0] if selected_sources else "demonstracao", model, index,
                            RunConfig(), key="draft/exp/fields", experimental=True)
    preview = st.button("Gerar plano sem inferência", type="primary", disabled=not ready)
    if preview:
        st.session_state.pop("plano_ui", None)
        try:
            config = Comparison(factory(), tuple(selected_sources), tuple(treatments),
                                tuple(int(part.strip()) for part in seeds.split(",")), repetitions, cap,
                                decision_mode, target, purpose, tuple(assignments))
            st.session_state["plano_ui"] = plan_comparison(config, workspace)
            st.session_state["plano_ui_id"] = uuid4().hex
        except ERRORS as exc:
            st.error(str(exc))
    plan = st.session_state.get("plano_ui")
    if plan:
        st.subheader("Plano congelado para confirmação")
        a, b, c = st.columns(3)
        a.metric("Sessões", plan["n_sessoes"])
        b.metric("Oportunidades", plan["n_oportunidades"])
        c.metric("Teto planejado de chat", plan["max_chat"])
        within_budget = plan["max_chat"] <= plan["configuracao"]["max_chat"]
        if not within_budget:
            st.warning("O teto planejado excede o orçamento. Ajuste o plano antes de executar.")
        st.write("O quadro identifica cada tratamento. A pré-verificação registra os digests antes de iniciar.")
        st.dataframe([{"Tratamento": label, "Arquitetura": spec["arquitetura"], "Gerador": spec["modelo"] or "Python"}
                      for label, spec in plan["tratamentos"].items()], hide_index=True, width="stretch")
        with st.expander("Parâmetros congelados, fontes e tratamentos"):
            st.json({"configuracao": plan["configuracao"], "fontes": plan["fontes"], "tratamentos": plan["tratamentos"]}, expanded=False)
        with st.form(f"launch-{plan['sha256']}"):
            confirmed = st.checkbox("Autorizo iniciar exatamente este plano e seu teto de chamadas.")
            submitted = st.form_submit_button("Executar plano", disabled=not within_budget)
        if submitted:
            try:
                identifier = start_comparison(plan, workspace, confirmed=confirmed,
                                              request_id=st.session_state["plano_ui_id"])
                st.session_state.pop("plano_ui", None)
                st.success(f"Experimento registrado · {identifier}")
            except ERRORS as exc:
                st.error(str(exc))
