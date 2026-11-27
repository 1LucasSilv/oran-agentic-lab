"""Recursos locais versionados usados pela interface e seus workers."""

from contextlib import ExitStack, contextmanager
from hashlib import sha256
from http.client import HTTPConnection
from io import BytesIO
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

import pandas as pd

from .detector import PRB, THROUGHPUT
from .dataset import dataset_digest
from .experiment import now, read_json, run_lock
from .ollama import AgentConfig, OllamaClient, strict_json
from .rag import Embedder, build_index, digest_json, load_index, model_tag, search
from .rag_corpus import DOCUMENTS, MANIFEST, verify_document
from .replay import validated_registers

SOURCE_ID = re.compile(r"(dataset|cenario)-[a-f0-9]{32}")
PRESET_ID = re.compile(r"preset-[a-f0-9]{32}")
TAG = re.compile(r"[\w][\w.-]{0,63}(?:/[\w][\w.-]{0,63}){0,2}(?::[\w][\w.-]{0,63})?", re.ASCII)
INDEX_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\.json")
FIELDS = ("Register", "UE.Id", THROUGHPUT, PRB)
UPLOAD_LIMIT = 16 * 1024 * 1024
ROW_LIMIT = 100_000
COLUMN_LIMIT = 256


def local_path(workspace, relative):
    path = workspace / relative
    if path.resolve() != workspace.resolve() / relative:
        raise ValueError("O recurso deve estar no caminho local autorizado.")
    return path


def label(name, maximum=100):
    name = name.strip()
    if not name or len(name) > maximum or any(not char.isprintable() for char in name):
        raise ValueError(f"Informe um texto de 1 a {maximum} caracteres imprimíveis.")
    return name


def upload_frames(filename, content, sheet=None):
    if not re.fullmatch(r"[^/\\:\x00-\x1f]{1,160}\.(csv|xlsx)", filename, re.I):
        raise ValueError("Selecione um nome de arquivo simples com extensão CSV ou XLSX.")
    if not 0 < len(content) <= UPLOAD_LIMIT:
        raise ValueError("O arquivo deve ter até 16 MiB.")
    if filename.lower().endswith(".csv"):
        if sheet is not None:
            raise ValueError("Um CSV tem apenas uma tabela.")
        table = pd.read_csv(BytesIO(content), encoding="utf-8-sig", nrows=ROW_LIMIT + 2, header=None)
        sheets = []
    else:
        try:
            with ZipFile(BytesIO(content)) as archive:
                members = archive.infolist()
                if len(members) > 512 or sum(m.file_size for m in members) > 64 * 1024 * 1024:
                    raise ValueError("O XLSX ultrapassa o limite de expansão.")
                if any(m.filename.endswith(("vbaProject.bin", ".exe")) for m in members):
                    raise ValueError("Use um XLSX sem macros.")
        except BadZipFile as error:
            raise ValueError("XLSX inválido.") from error
        with pd.ExcelFile(BytesIO(content), engine="openpyxl") as workbook:
            sheets = workbook.sheet_names
            selected = sheets[0] if sheet is None else sheet
            if selected not in sheets:
                raise ValueError("A aba selecionada não existe.")
            declared_columns = workbook.book[selected].max_column
            if declared_columns is not None and declared_columns > COLUMN_LIMIT:
                raise ValueError("A aba selecionada ultrapassa 256 colunas.")
            table = workbook.parse(selected, nrows=ROW_LIMIT + 2, header=None)
    if not 2 <= len(table) <= ROW_LIMIT + 1 or table.shape[1] > COLUMN_LIMIT:
        raise ValueError("Use entre 1 e 100.000 registros e até 256 colunas.")
    columns = table.iloc[0]
    if columns.isna().any() or len(set(columns.astype(str))) != len(columns):
        raise ValueError("O cabeçalho deve conter nomes de coluna preenchidos e únicos.")
    frame = table.iloc[1:].reset_index(drop=True)
    frame.columns = columns.astype(str).tolist()
    frame = frame.infer_objects()
    return frame, sheets


def audit_dataset(frame, mapping, ue=None):
    if set(mapping) != set(FIELDS) or len(set(mapping.values())) != len(FIELDS) or not set(mapping.values()) <= set(frame):
        raise ValueError("Mapeie os quatro campos para colunas distintas e existentes.")
    mapped = frame[[mapping[field] for field in FIELDS]].copy()
    mapped.columns = list(FIELDS)
    identifiers = mapped["UE.Id"].astype("string").str.strip()
    if (identifiers.isna() | identifiers.eq("")).any():
        raise ValueError("Há registros sem identificação de UE.")
    ues = sorted(identifiers.unique().tolist())
    if ue is None and len(ues) == 1:
        ue = ues[0]
    if ue not in ues:
        raise ValueError("Selecione explicitamente um UE da tabela.")
    result = mapped.loc[identifiers.eq(ue)].reset_index(drop=True)
    result["UE.Id"] = ue
    for field in ("Register", THROUGHPUT, PRB):
        original = result[field]
        numeric = pd.to_numeric(original, errors="coerce")
        if ((original.notna() & numeric.isna()) | numeric.abs().eq(float("inf")) | numeric.lt(0)).any():
            raise ValueError(f"{field} contém valor não numérico, infinito ou negativo no UE selecionado.")
        result[field] = numeric
    validated_registers(result)
    audit = {"linhas": len(frame), "linhas_replay": len(result), "colunas": list(frame),
             "tipos_inferidos": {k: str(v) for k, v in frame.dtypes.items()},
             "ausentes": frame.isna().sum().to_dict(), "duplicatas": int(frame.duplicated().sum()),
             "registros_duplicados_no_ue": int(result["Register"].duplicated().sum()),
             "ues": ues, "ue": ue, "mapeamento": mapping,
             "metricas_ausentes_no_ue": result[[THROUGHPUT, PRB]].isna().sum().to_dict(),
             "replay_compativel": True}
    return result, audit


def _store(workspace, category, prefix, payload, original=None):
    parent = local_path(workspace, Path("data/ui") / category)
    parent.mkdir(parents=True, exist_ok=True)
    identifier = f"{prefix}-{uuid4().hex}"
    payload = {"id": identifier, "data_utc": now(), **payload}
    envelope = {"conteudo": payload, "sha256": digest_json(payload)}
    with TemporaryDirectory(dir=parent) as folder:
        staged = Path(folder) / "registro"
        staged.mkdir()
        (staged / "manifesto.json").write_text(json.dumps(envelope, ensure_ascii=False, allow_nan=False),
                                              encoding="utf-8", newline="\n")
        if original:
            (staged / payload["original"]).write_bytes(original)
        staged.rename(parent / identifier)
    return payload


def import_dataset(workspace, name, filename, content, mapping, *, sheet=None, ue=None):
    frame, sheets = upload_frames(filename, content, sheet)
    normalized, audit = audit_dataset(frame, mapping, ue)
    return _store(workspace, "fontes", "dataset", {
        "nome": label(name), "tipo": "dataset_importado", "nome_de_origem": filename,
        "original": f"original{Path(filename).suffix.lower()}", "sha256_original": sha256(content).hexdigest(),
        "abas": sheets, "aba": (sheet or sheets[0]) if sheets else None, "auditoria": audit,
        "registros": json.loads(normalized.to_json(orient="records", double_precision=15)),
    }, content)


def synthetic_frame(segments):
    if not 1 <= len(segments) <= 64:
        raise ValueError("Defina de 1 a 64 segmentos.")
    records = []
    register = 1
    for segment in segments:
        count, gap = segment["registros"], segment["lacuna"]
        if type(count) is not int or type(gap) is not int or not 1 <= count <= 4096 or not 0 <= gap <= 100000:
            raise ValueError("Segmento com quantidade de registros ou lacuna inválida.")
        if len(records) + count > 10000:
            raise ValueError("O cenário admite até 10.000 registros.")
        register += gap
        records.extend({"Register": n, "UE.Id": "sintetico", THROUGHPUT: segment["throughput"],
                        PRB: segment["prb"]} for n in range(register, register + count))
        register += count
    frame, _ = audit_dataset(pd.DataFrame(records), {key: key for key in FIELDS})
    return frame


def save_scenario(workspace, name, description, segments, expectations=None):
    from .simulator import NO_ACTION, REGISTER_ALERT

    frame = synthetic_frame(segments)
    expectations = expectations or {}
    if any(not re.fullmatch(r"[1-9][0-9]{0,4}", str(key)) or action not in (NO_ACTION, REGISTER_ALERT)
           for key, action in expectations.items()):
        raise ValueError("Expectativas precisam de ID de janela positivo e ação conhecida.")
    return _store(workspace, "fontes", "cenario", {
        "tipo": "sintetico", "nome": label(name), "descricao": label(description, 1200), "segmentos": segments,
        "expectativas_declaradas": {str(k): v for k, v in expectations.items()},
        "registros": json.loads(frame.to_json(orient="records", double_precision=15)),
    })


def read_resource(workspace, identifier, pattern, category):
    if not pattern.fullmatch(identifier):
        raise ValueError("Identificador de recurso inválido.")
    directory = local_path(workspace, Path("data/ui") / category / identifier)
    relative = directory.relative_to(workspace)
    envelope = read_json(local_path(workspace, relative / "manifesto.json"))
    payload = envelope["conteudo"]
    if payload["id"] != identifier or digest_json(payload) != envelope["sha256"]:
        raise ValueError("A integridade do manifesto do recurso diverge.")
    if "original" in payload:
        filename = payload["original"]
        if filename not in ("original.csv", "original.xlsx"):
            raise ValueError("Formato original inválido.")
        with local_path(workspace, relative / filename).open("rb") as stream:
            original = stream.read(UPLOAD_LIMIT + 1)
        if len(original) > UPLOAD_LIMIT or sha256(original).hexdigest() != payload["sha256_original"]:
            raise ValueError("A integridade do arquivo original diverge.")
    return payload, envelope["sha256"]


def list_resources(workspace, category, pattern):
    folder = local_path(workspace, Path("data/ui") / category)
    resources = {}
    for directory in sorted(folder.glob("*")):
        if not pattern.fullmatch(directory.name):
            continue
        try:
            resources[directory.name] = read_resource(workspace, directory.name, pattern, category)[0]
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return resources


def custom_source(workspace, identifier):
    payload, checksum = read_resource(workspace, identifier, SOURCE_ID, "fontes")
    metadata = {k: v for k, v in payload.items() if k != "registros"}
    return pd.DataFrame(payload["registros"], columns=FIELDS), {**metadata, "sha256": checksum}


def save_preset(workspace, name, config):
    from dataclasses import asdict

    return _store(workspace, "presets", "preset", {"nome": label(name), "configuracao": asdict(config)})


def load_preset(workspace, identifier, *, preflight=None):
    from .ui_runs import RunConfig, prepare

    preset, _ = read_resource(workspace, identifier, PRESET_ID, "presets")
    config = RunConfig.from_dict(preset["configuracao"])
    (preflight or prepare)(config, workspace)
    return config


def import_preset(workspace, name, content, *, preflight=None):
    from .ui_runs import RunConfig, prepare

    if not 0 < len(content) <= 16384:
        raise ValueError("A configuração JSON deve ter até 16 KiB.")
    config = RunConfig.from_dict(strict_json(content.decode("utf-8-sig")))
    agent = config.agent
    if (config.replay.size > 4096 or config.replay.advance > 4096
            or config.detector.reference_windows > 100 or config.detector.persistence > 100
            or config.limits.max_history_size > 4096 or config.limits.history_budget > 100000
            or config.limits.min_inspection_stride > 4096
            or type(config.replay.include_partial) is not bool or type(config.start_paused) is not bool):
        raise ValueError("A configuração excede as faixas suportadas pela interface.")
    if agent and (agent.url != AgentConfig().url or not TAG.fullmatch(agent.model) or not 1 <= agent.timeout <= 600
                  or not 512 <= agent.num_ctx <= 131072 or agent.num_predict > 8192 or agent.max_calls > 4096
                  or agent.max_failures > 4096 or (agent.seed is not None and not -(2**31) <= agent.seed < 2**31)):
        raise ValueError("Gerador, endereço local ou limites de inferência incompatíveis com a interface.")
    (preflight or prepare)(config, workspace)
    return save_preset(workspace, name, config)


@contextmanager
def operation(workspace):
    """Uma única operação ativa entre workers operacionais, experimentos e manutenção."""
    from .ui_runs import _active_run, active_experiment, runs_root

    root = runs_root(workspace)
    with ExitStack() as locks:
        with run_lock(root):
            if _active_run(workspace) or active_experiment(workspace):
                raise ValueError("Já existe uma execução ativa.")
            locks.enter_context(run_lock(root / "worker"))
        yield


class ModelOperations:
    def __init__(self, config=AgentConfig()):
        self.url = urlsplit(config.url)

    def request(self, method, endpoint, payload):
        with_connection = HTTPConnection(self.url.hostname, self.url.port or 80, timeout=90)
        try:
            with_connection.request(method, endpoint, json.dumps(payload), {"Content-Type": "application/json"})
            with with_connection.getresponse() as response:
                if not 200 <= response.status < 300:
                    raise ValueError(f"Ollama HTTP {response.status}: {response.read(2048).decode('utf-8', 'replace')}")
                for line in iter(lambda: response.readline(65537), b""):
                    if len(line) > 65536:
                        raise ValueError("Resposta de gerenciamento do Ollama excede o limite.")
                    item = strict_json(line.decode("utf-8"))
                    if item.get("error"):
                        raise ValueError(str(item["error"]))
                    yield item
        finally:
            with_connection.close()


def inventory(client=None):
    client = client or OllamaClient(AgentConfig(timeout=3))
    version = client.info("/api/version").get("version")
    if not version:
        raise ValueError("Serviço Ollama local indisponível.")
    tags = client.info("/api/tags").get("models")
    running = client.info("/api/ps").get("models")
    if not isinstance(tags, list):
        raise ValueError("Inventário Ollama indisponível.")
    by_digest = {row.get("digest"): row for row in running or [] if row.get("digest")}
    models = []
    for item in tags:
        tag = item.get("name", "")
        if not TAG.fullmatch(tag) or tag.endswith((":cloud", "-cloud")) or item.get("remote_host") or item.get("remote_model"):
            continue
        status, raw = client.request("/api/show", {"model": tag})
        show = strict_json(raw) if status == 200 else {}
        detail = show.get("details") or item.get("details") or {}
        model_info = show.get("model_info", {})
        digest = item.get("digest")
        resident = by_digest.get(digest)
        models.append({"tag": tag, "digest": digest,
                       "arquitetura": model_info.get("general.architecture", detail.get("family")),
                       "parametros": model_info.get("general.parameter_count", detail.get("parameter_size")),
                       "quantizacao": detail.get("quantization_level"), "disco_bytes": item.get("size"),
                       "capacidades": show.get("capabilities") if status == 200 else None,
                       "residente": digest in by_digest if isinstance(running, list) and digest else None,
                       "residencia_bytes": resident.get("size") if resident else None,
                       "vram_reportada_bytes": resident.get("size_vram") if resident else None})
    return version, models


def model_references(workspace, tag, digest):
    from .ui_runs import available_indices

    references = [str(path) for path, doc in historical_manifests(workspace) if _references(doc, tag, digest)]
    for name in available_indices(workspace):
        if _references(inspect_index(workspace, name)["metadados"], tag, digest):
            references.append(f"data/rag/{name}")
    return references


def pull_model(workspace, tag, *, confirmed=False, progress=lambda item: None, api=None, client=None):
    if not confirmed or not TAG.fullmatch(tag) or tag.endswith((":cloud", "-cloud")):
        raise ValueError("Confirme um nome de modelo local válido para baixar.")
    with operation(workspace):
        _, models = inventory(client)
        if any(row["tag"] == model_tag(tag) for row in models):
            raise ValueError("A tag já está instalada. Use uma tag diferente para preservar a versão disponível.")
        last = None
        for last in (api or ModelOperations()).request("POST", "/api/pull", {"model": tag, "stream": True}):
            progress(last)
        if not last or last.get("status") != "success":
            raise ValueError("O download terminou sem confirmação de sucesso do Ollama.")


def _references(value, tag, digest):
    if isinstance(value, dict):
        return any(_references(child, tag, digest) for child in value.values())
    if isinstance(value, list):
        return any(_references(child, tag, digest) for child in value)
    if not isinstance(value, str):
        return False
    value = value.replace("\\", "/").casefold()
    tag = tag.casefold()
    return (value == digest or value == tag or value == tag.removesuffix(":latest")
            or (tag.endswith(".json") and value.endswith(f"/{tag}")))


def historical_manifests(workspace):
    root = local_path(workspace, Path("results"))
    for pattern in ("ui/*/manifesto.json", "ui/experimentos/*/manifesto.json", "etapa6/**/resultados.json",
                    "etapa7/**/manifesto.json",
                    "etapa7/**/plano.json"):
        for path in root.glob(pattern):
            path = local_path(workspace, path.relative_to(workspace))
            yield path, read_json(path)
    for preset in list_resources(workspace, "presets", PRESET_ID).values():
        yield Path("data/ui/presets") / preset["id"], preset


def delete_model(workspace, tag, *, confirmed=False, client=None, api=None):
    if not confirmed or not TAG.fullmatch(tag):
        raise ValueError("Confirme o nome exato do modelo para remover.")
    with operation(workspace):
        _, models = inventory(client)
        selected = next((row for row in models if row["tag"] == tag), None)
        if not selected or selected["residente"] is not False:
            raise ValueError("O modelo deve estar instalado e comprovadamente fora de memória.")
        digest = selected["digest"]
        references = model_references(workspace, tag, digest)
        if references:
            raise ValueError("O modelo é referenciado por " + ", ".join(references[:12]))
        list((api or ModelOperations()).request("DELETE", "/api/delete", {"model": tag}))


def corpus_status(workspace):
    folder = local_path(workspace, DOCUMENTS)
    entries = []
    for document in MANIFEST:
        try:
            verify_document(local_path(workspace, DOCUMENTS / document["arquivo"]), document)
            status = "verificado"
        except (OSError, ValueError) as error:
            status = str(error)
        entries.append({**document, "integridade_local": status})
    return folder, entries


def inspect_index(workspace, name, identity=None):
    from .ui_runs import FILENAME

    if not FILENAME.fullmatch(name):
        raise ValueError("Nome de índice inválido.")
    path = local_path(workspace, Path("data/rag") / name)
    content = load_index(path, identity)
    return {**content, "tamanho_bytes": path.stat().st_size}


def create_index(workspace, name, embedder, *, confirmed=False, replace=False):
    if not confirmed or not INDEX_NAME.fullmatch(name):
        raise ValueError("Confirme a indexação e informe um nome JSON simples.")
    folder, entries = corpus_status(workspace)
    if any(row["integridade_local"] != "verificado" for row in entries):
        raise ValueError("O corpus oficial precisa estar localmente disponível e verificado.")
    path = local_path(workspace, Path("data/rag") / name)
    with operation(workspace):
        if path.exists() and not replace:
            raise ValueError("Já existe um índice com este nome. Use um novo nome ou autorize a substituição.")
        if path.exists():
            identity = inspect_index(workspace, name)
            stored_digest = dataset_digest(path)
            if any(_references(doc, name, stored_digest) or _references(doc, name, identity["sha256"])
                   for _, doc in historical_manifests(workspace)):
                raise ValueError("O índice tem referências históricas ou em presets. Crie outro nome.")
            archive = local_path(workspace, Path("data/rag/historico") / f"{path.stem}-{uuid4().hex}.json")
            archive.parent.mkdir(parents=True, exist_ok=True)
            with archive.open("xb") as stream:
                stream.write(path.read_bytes())
        return build_index(folder, path, embedder)


def query_index(workspace, name, embedder, query, top_k=2, min_score=0.35):
    query = label(query, 1500)
    with operation(workspace):
        index = inspect_index(workspace, name, embedder.identity())
        return search(index, embedder, query, top_k, min_score)
