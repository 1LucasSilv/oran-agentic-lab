from io import BytesIO
from dataclasses import asdict
import json

import pandas as pd
import pytest

from oran_lab.detector import PRB, THROUGHPUT
from oran_lab.experiment import atomic_json
from oran_lab.ui_resources import (
    FIELDS, audit_dataset, create_index, custom_source, delete_model, import_dataset, import_preset, inspect_index,
    inventory, load_preset, pull_model, save_preset, save_scenario, upload_frames,
)
from oran_lab.ui_runs import RunConfig, data_source

CSV = b"reg,ue,ul,prb\n1,alpha,10,40\n2,alpha,,40\n4,alpha,20,42\n1,beta,80,40\n"
MAPPING = dict(zip(FIELDS, ("reg", "ue", "ul", "prb"), strict=True))
DIGEST = "a" * 64


class ModelClient:
    def info(self, path):
        return {"/api/version": {"version": "1"}, "/api/tags": {"models": [
            {"name": "test:1", "digest": DIGEST, "size": 123}]}, "/api/ps": {"models": []}}[path]

    def request(self, path, data):
        assert path == "/api/show" and data == {"model": "test:1"}
        return 200, '{"capabilities":["completion"],"details":{"family":"test","parameter_size":"1B"}}'


class ModelAPI:
    def __init__(self):
        self.requests = []

    def request(self, *args):
        self.requests.append(args)
        return iter([{"status": "success"}]) if args[0] == "POST" else iter([])


def test_model_inventory_and_protected_operations(tmp_path):
    client, api = ModelClient(), ModelAPI()
    version, models = inventory(client)
    assert version == "1"
    assert models[0]["disco_bytes"] == 123 and models[0]["vram_reportada_bytes"] is None
    with pytest.raises(ValueError, match="Confirme"):
        pull_model(tmp_path, "other", api=api)
    with pytest.raises(ValueError, match="já está instalada"):
        pull_model(tmp_path, "test:1", confirmed=True, api=api, client=client)
    progress = []
    pull_model(tmp_path, "other", confirmed=True, api=api, client=client, progress=progress.append)
    assert progress == [{"status": "success"}]
    atomic_json(tmp_path / "results/etapa7/science/manifesto.json", {"digest": DIGEST})
    with pytest.raises(ValueError, match="science"):
        delete_model(tmp_path, "test:1", confirmed=True, api=api, client=client)
    assert len(api.requests) == 1
    independent = tmp_path / "isolado"
    delete_model(independent, "test:1", confirmed=True, api=api, client=client)
    assert api.requests[-1] == ("DELETE", "/api/delete", {"model": "test:1"})


def test_dataset_immutability_and_ue(tmp_path):
    frame, sheets = upload_frames("kpm.csv", CSV)
    assert not sheets
    with pytest.raises(ValueError, match="UE"):
        audit_dataset(frame, MAPPING)
    saved = import_dataset(tmp_path, "Amostra", "kpm.csv", CSV, MAPPING, ue="alpha")
    config = RunConfig(source=saved["id"])
    normalized, origin = data_source(config, tmp_path)
    assert origin["auditoria"]["metricas_ausentes_no_ue"][THROUGHPUT] == 1
    assert list(normalized.Register) == [1, 2, 4] and set(normalized["UE.Id"]) == {"alpha"}
    original = tmp_path / "data/ui/fontes" / saved["id"] / "original.csv"
    assert original.read_bytes() == CSV
    original.write_bytes(b"alterado")
    with pytest.raises(ValueError, match="original diverge"):
        custom_source(tmp_path, saved["id"])
    with pytest.raises(ValueError, match="nome"):
        upload_frames("../kpm.csv", CSV)
    with pytest.raises(ValueError, match="duplicado"):
        import_dataset(tmp_path, "Amostra", "kpm.csv", CSV + b"4,alpha,12,30\n", MAPPING, ue="alpha")


def test_xlsx_audit_and_sheet_selection():
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        upload_frames("kpm.csv", CSV)[0].to_excel(writer, sheet_name="KPM", index=False)
    frame, sheets = upload_frames("kpm.xlsx", buffer.getvalue(), "KPM")
    assert sheets == ["KPM"] and len(frame) == 4
    with pytest.raises(ValueError, match="aba"):
        upload_frames("kpm.xlsx", buffer.getvalue(), "outra")


def test_synthetic_and_preset_are_versioned(tmp_path):
    segments = [{"registros": 2, "lacuna": 0, "throughput": 10, "prb": 40},
                {"registros": 1, "lacuna": 3, "throughput": None, "prb": 35}]
    saved = save_scenario(tmp_path, "Cenário", "Lacuna experimental", segments, {1: "nenhuma_acao"})
    duplicate = save_scenario(tmp_path, "Cenário", "Lacuna experimental", segments)
    config = RunConfig(source=saved["id"])
    frame, metadata = data_source(config, tmp_path)
    assert duplicate["id"] != saved["id"] and metadata["tipo"] == "sintetico"
    assert list(frame.Register) == [1, 2, 6] and pd.isna(frame.iloc[-1][THROUGHPUT])
    assert frame.iloc[-1][PRB] == 35
    preset = save_preset(tmp_path, "Rodar cenário", config)
    assert load_preset(tmp_path, preset["id"]) == config
    raw = json.dumps(asdict(config)).encode("utf-8")
    imported = import_preset(tmp_path, "Importado", raw)
    assert imported["id"] != preset["id"]
    assert load_preset(tmp_path, imported["id"]) == config
    with pytest.raises(ValueError, match="16 KiB"):
        import_preset(tmp_path, "Inválido", b"x" * 16385)
    path = tmp_path / "data/ui/fontes" / saved["id"] / "manifesto.json"
    path.unlink()
    with pytest.raises(FileNotFoundError):
        load_preset(tmp_path, preset["id"])


def test_index_name_and_compatibility_are_checked(tmp_path, monkeypatch):
    def checked(path, identity):
        assert path == tmp_path / "data/rag/validado.json"
        if identity != {"modelo": "embed:1", "digest": DIGEST}:
            raise ValueError("Índice incompatível")
        return {"metadados": {"dimensao": 2}}

    monkeypatch.setattr("oran_lab.ui_resources.load_index", checked)
    index = tmp_path / "data/rag/validado.json"
    index.parent.mkdir(parents=True)
    index.write_bytes(b"{}")
    with pytest.raises(ValueError, match="incompatível"):
        inspect_index(tmp_path, "validado.json", {"modelo": "outro"})
    assert inspect_index(tmp_path, "validado.json", {"modelo": "embed:1", "digest": DIGEST})["tamanho_bytes"] == 2
    with pytest.raises(ValueError, match="Nome"):
        inspect_index(tmp_path, "../../validado.json")


def test_index_replacement_requires_confirmation_and_protects_history(tmp_path, monkeypatch):
    index = tmp_path / "data/rag/validado.json"
    index.parent.mkdir(parents=True)
    index.write_bytes(b"indice original")
    monkeypatch.setattr("oran_lab.ui_resources.corpus_status",
                        lambda workspace: (index.parent, [{"integridade_local": "verificado"}]))
    monkeypatch.setattr("oran_lab.ui_resources.inspect_index", lambda *args: {"sha256": DIGEST})

    def build(folder, output, embedder):
        assert folder == index.parent and output == index
        output.write_bytes(b"novo indice")
        return {"fragmentos": 1}

    monkeypatch.setattr("oran_lab.ui_resources.build_index", build)
    with pytest.raises(ValueError, match="Confirme"):
        create_index(tmp_path, index.name, object())
    with pytest.raises(ValueError, match="Já existe"):
        create_index(tmp_path, index.name, object(), confirmed=True)
    assert create_index(tmp_path, index.name, object(), confirmed=True, replace=True) == {"fragmentos": 1}
    [archive] = list((index.parent / "historico").glob("*.json"))
    assert archive.read_bytes() == b"indice original"
    atomic_json(tmp_path / "results/etapa7/bateria/plano.json", {"index": r"data\rag\Validado.json"})
    with pytest.raises(ValueError, match="referências históricas"):
        create_index(tmp_path, index.name, object(), confirmed=True, replace=True)
    assert index.read_bytes() == b"novo indice"
