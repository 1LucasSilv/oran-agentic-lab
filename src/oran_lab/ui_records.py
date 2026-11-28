"""Consulta local de execuções, reprodução e avaliação a partir de registros persistidos."""

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import pandas as pd

from .experiment import read_json, run_lock
from .experiment_report import RUBRIC, architecture, flatten, import_reviews, read_experiment
from .ui_runs import ARCHITECTURES, ID, SOURCES, local_path, manifest_order, read_snapshot, recorded_time, publish
from .ui_resources import label

SAFE_SESSION = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,159}")
REVIEW_FILES = ("avaliacao-cega.csv", "avaliacao-referencias.json", "chave-avaliacao-local.json")
STATE_LABELS = {"iniciando": "Iniciando", "preparando": "Preparando", "executando": "Em execução",
                "pausada": "Pausada", "concluida": "Concluída", "interrompida": "Interrompida",
                "falha": "Falha", "com_falhas": "Com falhas", "parcial": "Parcial", "pendente": "Pendente"}
UNRECORDED = "Sem registro"


@dataclass(frozen=True)
class Recording:
    folder: Path
    kind: str
    key: str
    started: datetime | None = None
    state: str | None = None
    sources: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    architectures: tuple[str, ...] = ()
    name: str = ""
    description: str = ""

    @property
    def identity(self):
        return f"{self.kind}/{self.key}"

    @property
    def legacy_title(self):
        return f"{self.kind} · {self.key}"

    @property
    def automatic_name(self):
        noun = {"Operacional": "Execução", "Configurável": "Experimento", "Etapa 7": "Etapa 7"}[self.kind]
        source = short_list(self.sources)
        arch = short_list(self.architectures)
        return " · ".join(item for item in (noun, source, arch) if item)

    @property
    def title(self):
        return self.name or self.automatic_name

    @property
    def local_start(self):
        return local_time(self.started)

    @property
    def state_label(self):
        return STATE_LABELS.get(self.state, self.state or UNRECORDED)

    @property
    def context(self):
        return " · ".join(filter(None, (short_list(self.sources), short_list(self.models), architecture_label(self.architectures))))

    @property
    def selector_label(self):
        details = [short_list(self.sources), short_list(self.models), architecture_label(self.architectures),
                   self.local_start, self.state_label]
        return " · ".join([self.title, *(item for item in details if item and item not in self.title)])


def local_time(value):
    return value.astimezone().strftime("%d/%m/%Y %H:%M:%S") if value else None


def short_list(values, limit=2):
    return ", ".join(values[:limit]) + (f" +{len(values) - limit}" if len(values) > limit else "")


def source_label(key, metadata=None):
    metadata = metadata or {}
    return metadata.get("nome") or SOURCES.get(key) or metadata.get("arquivo") or (key.replace("-", " ") if key else "")


def architecture_label(codes):
    if not codes:
        return ""
    label_text = ", ".join(f"{code} · {ARCHITECTURES[code]}" if code in ARCHITECTURES else code for code in codes)
    return label_text if len(codes) <= 2 else f"{', '.join(codes)} · MCP/RAG por tratamento"


def session_label(job, model=None, source=None, *, started=None, state=None):
    treatment = job.get("tratamento", {})
    arch = treatment.get("architecture", job.get("configuracao"))
    agent = treatment.get("agent") or {}
    model = agent.get("model") or (model if arch != "A" else None)
    details = (source or source_label(job.get("caso")), model, architecture_label((arch,)) if arch else None,
               f"Semente {job['seed']}" if job.get("seed") is not None else None,
               f"Repetição {job['repeticao']}" if job.get("repeticao") is not None else None,
               local_time(recorded_time(started)), STATE_LABELS.get(state, state) if state else None)
    return " · ".join([*(item for item in details if item), job["id"]])


def visual_path(workspace, record):
    token = sha256(record.identity.encode("utf-8")).hexdigest()[:24]
    return local_path(workspace, Path("results/ui/identificacao") / f"{token}.json")


def clean_name(value):
    return label(value, 100) if value.strip() else ""


def save_identity(workspace, record, name, description=""):
    cleaned = clean_name(name)
    description = description.strip()
    if len(description) > 2000 or any(not (char.isprintable() or char in "\n\r\t") for char in description):
        raise ValueError("A descrição deve ter até 2.000 caracteres de texto.")
    path = visual_path(workspace, record)
    publish(path, {"identidade": record.identity, "nome": cleaned, "descricao": description})


def historical_state(folder):
    rows = stored(folder, "relatorios/decisoes.json", [])
    states = {row.get("estado_execucao") for row in rows}
    if states == {"concluida"}:
        return "concluida"
    if "pendente" in states or "parcial" in states:
        return "parcial"
    if "falha" in states:
        return "com_falhas" if "concluida" in states else "falha"
    return next(iter(states)) if len(states) == 1 else None


def describe_record(workspace, entry, manifest, plan):
    config = manifest.get("configuracao", {})
    resources = manifest.get("recursos", {})
    if entry.kind == "Operacional":
        source = source_label(config.get("source"), resources.get("fonte"))
        model = (config.get("agent") or {}).get("model") or (resources.get("gerador") or {}).get("tag")
        architectures = (config["architecture"],) if config.get("architecture") else ()
        models = (model,) if model else ()
        sources = (source,) if source else ()
    else:
        jobs = plan.get("execucoes", [])
        architectures = tuple(sorted({arch for job in jobs if (arch := architecture(job))}))
        model = plan.get("inferencia", {}).get("modelo")
        observed_models = set()
        for job in jobs:
            options = job.get("tratamento", {}).get("agent") or {}
            if architecture(job) != "A" and (tag := options.get("model") or model):
                observed_models.add(tag)
        models = tuple(sorted(observed_models))
        descriptors = plan.get("fontes", {})
        sources = tuple(dict.fromkeys(source_label(key, descriptors.get(key, {}).get("origem"))
                                      for job in jobs if (key := job.get("caso"))))
    state = stored(entry.folder, "status.json", {}).get("estado")
    if not state and entry.kind == "Etapa 7":
        state = historical_state(entry.folder)
    path = visual_path(workspace, entry)
    visual = stored(path.parent, path.name, {})
    if visual.get("identidade") != entry.identity:
        visual = {}
    return Recording(entry.folder, entry.kind, entry.key, recorded_time(manifest.get("inicio_utc")),
                     state, sources, models, architectures, visual.get("nome", ""), visual.get("descricao", ""))


def recordings(workspace, kinds=None):
    groups = (("Operacional", "results/ui", "*/manifesto.json"),
              ("Configurável", "results/ui/experimentos", "*/plano.json"),
              ("Etapa 7", "results/etapa7", "**/plano.json"))
    records = []
    for kind, root, pattern in groups:
        if kinds is not None and kind not in kinds:
            continue
        base = local_path(workspace, Path(root))
        for file in sorted(base.glob(pattern), reverse=True):
            if kind != "Etapa 7" and not ID.fullmatch(file.parent.name):
                continue
            try:
                local_path(workspace, file.relative_to(workspace))
            except ValueError:
                continue
            name = file.parent.relative_to(base).as_posix()
            entry = Recording(file.parent, kind, name)
            manifest = stored(file.parent, "manifesto.json", {})
            plan = stored(file.parent, "plano.json", {}) if kind != "Operacional" else {}
            records.append(describe_record(workspace, entry, manifest, plan))
    records.sort(key=lambda entry: entry.started or manifest_order({}), reverse=True)
    return {entry.identity: entry for entry in records}


def stored(folder, filename, default=None):
    path = folder / filename
    if not path.is_file():
        return default
    if path.resolve() != folder.resolve() / filename:
        raise ValueError("Registro fora do caminho autorizado.")
    return read_snapshot(path)


def plan_for(record):
    plan = stored(record.folder, "plano.json", {})
    for job in plan.get("execucoes", []):
        name = job["id"]
        if not SAFE_SESSION.fullmatch(name):
            raise ValueError("Identificador de sessão inválido no plano.")
        relative = Path("execucoes") / name
        folder = record.folder / relative
        if folder.resolve() != record.folder.resolve() / relative:
            raise ValueError("Sessão fora do caminho autorizado.")
        for name in ("eventos", "chat"):
            path = folder / name
            if path.is_symlink() or any(file.is_symlink() for file in path.glob("*.json")):
                raise ValueError("Os arquivos de sessão precisam permanecer no diretório autorizado.")
        if (folder / "resultado.json").is_symlink():
            raise ValueError("Resultado de sessão fora do diretório autorizado.")
    return plan


def granular(record, after=0):
    name = "eventos" if record.kind == "Operacional" else "diario"
    diary = record.folder / name
    if diary.resolve() != record.folder.resolve() / name:
        raise ValueError("Diário fora do caminho autorizado.")
    return [stored(record.folder, f"{name}/{path.name}") for path in sorted(diary.glob("*.json"))
            if path.stem.isdecimal() and int(path.stem) > after]


def recording_events(record):
    events = granular(record)
    if events or record.kind == "Operacional":
        return events, True
    plan = plan_for(record)
    for job in plan.get("execucoes", []):
        base = f"execucoes/{job['id']}"
        for number in job["janelas"]:
            window = stored(record.folder, f"{base}/eventos/janela-{number:04d}.json")
            if window is not None:
                events.append({"seq": len(events) + 1, "janela": number, "sessao": job["id"],
                               "data_utc": window.get("data"), "componente": "janela",
                               "estado": "concluida", "dados": window})
        end = stored(record.folder, f"{base}/resultado.json")
        if end is not None:
            events.append({"seq": len(events) + 1, "janela": None, "sessao": job["id"],
                           "data_utc": end.get("data"), "componente": "sessao",
                           "estado": end["estado"], "dados": end})
    return events, False


def replay_prefix(events, position):
    return events[:max(0, min(position, len(events)))]


def next_window(events, position):
    return next((index for index, event in enumerate(events, 1)
                 if index > position and event["componente"] == "janela"), len(events))


def progress(record, plan, events):
    totals, treatment = {}, {}
    jobs = {job["id"]: job for job in plan.get("execucoes", [])}
    active_id = next((event.get("sessao") for event in reversed(events) if event.get("sessao")), None)
    reserved = returned = 0
    for sid, job in jobs.items():
        base = record.folder / "execucoes" / sid
        end = stored(record.folder, f"execucoes/{sid}/resultado.json", {})
        state = end.get("estado", "pendente")
        if not end and sid == active_id and events[-1]["componente"] != "experimento":
            state = "em_curso"
        windows = sum((base / "eventos" / f"janela-{n:04d}.json").is_file() for n in job["janelas"])
        starts = list((base / "chat").glob("*-inicio.json"))
        reserved += len(starts)
        returned += sum(path.with_name(path.name.replace("-inicio", "-fim")).is_file() for path in starts)
        for group in (totals, treatment.setdefault(job["configuracao"], {})):
            for key, count in (("planejadas", 1), (state, 1), ("janelas", len(job["janelas"])),
                               ("processadas", windows), ("reservas", len(starts))):
                group[key] = group.get(key, 0) + count
    return totals, treatment, reserved, returned


def elapsed(manifest, snapshot):
    start = manifest.get("inicio_utc")
    if not start:
        return None
    finish = snapshot.get("data_utc") if snapshot.get("estado") in ("concluida", "falha", "interrompida") else None
    end = datetime.fromisoformat(finish) if finish else datetime.now(timezone.utc)
    return max(0, (end - datetime.fromisoformat(start)).total_seconds())


def operational_windows(record):
    result = stored(record.folder, "resultados.json", {})
    if result:
        history = result["simulador"]["historico"]
        by_window = {}
        for entry in history:
            by_window.setdefault(entry["janela_id"], []).append(entry)
        audits = {a["janela_id"]: a for a in result.get("agente", {}).get("decisoes", [])}
        return [{"janela": d["janela"]["id"], "detector": d, "agente": audits.get(d["janela"]["id"]),
                 "historico": by_window.get(d["janela"]["id"], [])} for d in result["deteccoes"]]
    events = granular(record)
    detections = {e["janela"]: e["dados"]["deteccao"] for e in events
                  if e["componente"] == "detector" and "deteccao" in e["dados"]}
    return [{"janela": e["janela"], **e["dados"], "detector": detections.get(e["janela"])}
            for e in events if e["componente"] == "janela" and e["estado"] == "concluida"]


def result_rows(record):
    manifest = stored(record.folder, "manifesto.json", {})
    if record.kind == "Operacional":
        config = manifest.get("configuracao", {})
        job = {"id": record.key, "caso": config.get("source"), "configuracao": config.get("architecture", "A"),
               "seed": (config.get("agent") or {}).get("seed"), "tratamento": config}
        windows = operational_windows(record)
        snapshot = stored(record.folder, "status.json", {"estado": "desconhecido"})
        rows = [flatten(job, event["janela"], dict(event, agente=dict(event.get("agente") or {},
                 proposta_original=(event.get("agente") or {}).get("proposta_modelo"))), [],
                 snapshot) for event in windows]
        for row, event in zip(rows, windows, strict=True):
            for key in ("chat_reservadas", "chat_sem_retorno", "chat_falha_comunicacao", "chat_decisao",
                        "chat_mcp", "decisao_final_nao_consultada"):
                row[key] = None
            row["repeticao"] = None
            audit = event.get("agente") or {}
            times = [call["tempo_chamada_s"] for call in [*audit.get("inferencias_consulta", ()), audit]
                     if call.get("tempo_chamada_s") is not None]
            row["tempo_chat_s"] = sum(times) if times else None
            row.update(verified_changes(event))
        return rows
    plan = plan_for(record)
    generator = plan.get("inferencia", {}).get("modelo")
    rows = []
    for job, window, event, chats, execution, _ in read_experiment(record.folder):
        row = flatten(job, window, event, chats, execution)
        row.setdefault("arquitetura", architecture(job))
        row.setdefault("repeticao", job.get("repeticao"))
        row.setdefault("modelo", generator if architecture(job) != "A" else None)
        row.update(verified_changes(event))
        rows.append(row)
    return rows


def verified_changes(event):
    final = (event.get("historico") or [{}])[-1] if event else {}
    changed = (final.get("execucao", {}).get("estado") == "executada"
               and final.get("verificacao", {}).get("estado") == "aprovada") if final else None
    return {"mudanca_verificada": changed, "mudanca_verificada_modelo": changed and final.get("origem") == "ollama"}


def filter_rows(rows, filters):
    return [row for row in rows if all(not allowed or row.get(key) in allowed for key, allowed in filters.items())]


def compatibility(record):
    plan = plan_for(record)
    manifest = stored(record.folder, "manifesto.json", {})
    resources = manifest.get("recursos", {})
    config = manifest.get("configuracao", plan.get("configuracao", plan.get("parametros", {})))
    model = resources.get("gerador", {})
    datasets = plan.get("fontes", plan.get("casos", resources.get("fonte")))
    prompt = plan.get("prompt_sha256") or plan.get("inferencia", {}).get("prompt_sha256")
    if record.kind == "Operacional":
        prompt = stored(record.folder, "resultados.json", {}).get("agente", {}).get("prompt_sha256")
    return {
        "Protocolo": {"origem": record.kind, "modo": config.get("mode", config.get("modo")),
                      "finalidade": config.get("purpose", config.get("phase")),
                      "versao": plan.get("versao", plan.get("formato"))},
        "Dados e hashes": datasets,
        "Prompt": prompt,
        "Parâmetros": {"configuracao": config, "inferencia": plan.get("inferencia"), "rag": plan.get("rag")},
        "Hardware": manifest.get("hardware") or
        ({key: resources.get(key) for key in ("sistema", "cpu", "arquitetura", "ram_bytes")}
         if resources.get("cpu") else model.get("processador_host")),
        "Digests": {key: value for key, value in resources.items() if key != "fonte"},
    }


def compare_records(first, second):
    a, b = compatibility(first), compatibility(second)
    return [{"dimensao": name, "estado": "indeterminado" if a[name] is None or b[name] is None
             else "igual" if a[name] == b[name] else "diferente", "primeira": a[name], "segunda": b[name]}
            for name in a]


def review_folder(workspace, record):
    original = record.folder / "relatorios"
    overlay = local_path(workspace, Path("results/ui/avaliacoes") / sha256(record.legacy_title.encode("utf-8")).hexdigest()[:24])
    return overlay, original


def review_material(workspace, record):
    overlay, original = review_folder(workspace, record)
    if original.resolve() != record.folder.resolve() / "relatorios" or any(
            (original / filename).is_symlink() for filename in REVIEW_FILES):
        raise ValueError("O material de revisão deve estar no diretório autorizado.")
    with (original / REVIEW_FILES[0]).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    refs = {row["id"]: row for row in stored(original, REVIEW_FILES[1], [])}
    return overlay, rows, refs


def review_mcp(record, opaque_id):
    mapping = stored(record.folder, f"relatorios/{REVIEW_FILES[2]}", {})
    mapped = mapping.get(opaque_id)
    if not mapped or not SAFE_SESSION.fullmatch(mapped["execucao"]):
        return []
    plan_for(record)
    window = stored(record.folder, f"execucoes/{mapped['execucao']}/eventos/janela-{int(mapped['janela']):04d}.json", {})
    audit = window.get("agente") or {}
    return [{"consulta": entry["nome"], "evidencia": entry["resultado"]}
            for entry in (audit.get("mcp") or {}).get("ferramentas", [])
            if entry.get("nome") in ("consultar_janela", "consultar_historico") and entry.get("resultado") is not None]


def reviewer_records(workspace, record, evaluator):
    overlay, _ = review_folder(workspace, record)
    reviewed = {}
    for folder in (record.folder / "avaliacoes", overlay / "avaliacoes"):
        batches = [stored(folder, path.name) for path in folder.glob("*.json") if not path.name.startswith("legado-")]
        for batch in sorted(batches, key=lambda x: x["data_utc"]):
            if batch.get("avaliador") != evaluator:
                continue
            for key, row in batch["avaliacoes"].items():
                prior = reviewed.setdefault(key, {"pontuacoes": {}, "comentario": ""})
                prior["pontuacoes"].update({k: v for k, v in row["pontuacoes"].items() if v is not None})
                if row.get("comentario"):
                    prior["comentario"] = row["comentario"]
    return reviewed


def review_csv(rows):
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=["id", *RUBRIC, "avaliador", "comentario"], extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def save_reviews(workspace, record, evaluator, data, *, revise=False):
    evaluator = label(evaluator)
    if not 0 < len(data) <= 1_048_576:
        raise ValueError("O CSV deve ter até 1 MiB.")
    overlay, original = review_folder(workspace, record)
    with run_lock(overlay / "edicao"):
        current = reviewer_records(workspace, record, evaluator)
        reader = csv.DictReader(StringIO(data.decode("utf-8-sig")))
        if not {"id", *RUBRIC} <= set(reader.fieldnames or ()):
            raise ValueError("Colunas da rubrica ausentes.")
        changed, seen = [], set()
        for row in reader:
            key = row["id"]
            if key in seen:
                raise ValueError("ID duplicado no CSV.")
            seen.add(key)
            if row.get("avaliador") and row["avaliador"] != evaluator:
                raise ValueError("O avaliador indicado diverge do CSV.")
            prior = current.get(key, {})
            for criterion in RUBRIC:
                row[criterion] = (row.get(criterion) or "").strip()
            for criterion, score in prior.get("pontuacoes", {}).items():
                if row.get(criterion) == str(score):
                    row[criterion] = ""
                elif row.get(criterion) and not revise:
                    raise ValueError("Autorize a revisão de notas já registradas.")
            comment = row.get("comentario")
            if comment and comment == prior.get("comentario"):
                row["comentario"] = ""
            elif comment and prior.get("comentario") and not revise:
                raise ValueError("Autorize a revisão de comentários já registrados.")
            if any(row.get(field) for field in (*RUBRIC, "comentario")):
                changed.append(row)
        if not changed:
            return 0
        output = overlay / "relatorios"
        output.mkdir(parents=True, exist_ok=True)
        for filename in REVIEW_FILES:
            target = output / filename
            if target.is_symlink():
                raise ValueError("Material de avaliação fora do diretório autorizado.")
            if not target.exists():
                target.write_bytes((original / filename).read_bytes())
        for prior_file in (record.folder / "avaliacoes").glob("*.json"):
            target = overlay / "avaliacoes" / f"legado-{prior_file.name}"
            if not target.exists():
                target.parent.mkdir(exist_ok=True)
                target.write_bytes(prior_file.read_bytes())
        with TemporaryDirectory(dir=overlay) as tmp:
            path = Path(tmp) / "avaliacao.csv"
            path.write_bytes(review_csv(changed))
            return import_reviews(overlay, path, evaluator=evaluator)["avaliacoes"]
