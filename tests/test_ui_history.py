"""Identidade visual e ordenação sem dependência de execução real."""

from hashlib import sha256
from pathlib import Path

import pytest

from oran_lab.experiment import atomic_json
from oran_lab.ui_records import recordings, review_folder, reviewer_records, save_identity, session_label
from oran_lab.ui_runs import list_runs


def operational_record(workspace, key, timestamp, *, architecture="E", state="concluida"):
    folder = workspace / "results/ui" / key
    manifest = {"id": key, "configuracao": {"architecture": architecture, "source": "demonstracao",
                                          "agent": {"model": "fixture:1"} if architecture != "A" else None}}
    if timestamp:
        manifest["inicio_utc"] = timestamp
    atomic_json(folder / "manifesto.json", manifest)
    atomic_json(folder / "status.json", {"estado": state})
    return folder


def test_catalog_orders_registered_instants_and_retains_missing_metadata(tmp_path):
    old, new = "f" * 32, "a" * 32
    operational_record(tmp_path, old, "2026-11-28T04:00:00+02:00")
    operational_record(tmp_path, new, "2026-11-28T00:30:00-03:00")
    legacy = tmp_path / "results/etapa7/antigo"
    atomic_json(legacy / "plano.json", {})
    entries = list(recordings(tmp_path).values())
    assert [entry.key for entry in entries] == [new, old, "antigo"]
    assert [manifest["id"] for manifest in list_runs(tmp_path)] == [new, old]
    assert [entries[-1].started, entries[-1].local_start, entries[-1].state] == [None, None, None]
    assert entries[-1].sources == entries[-1].models == () and entries[-1].title == "Etapa 7"
    assert "demonstração" in entries[0].title
    assert "fixture:1" in entries[0].selector_label and "MCP + RAG" in entries[0].selector_label
    assert entries[0].local_start == entries[0].started.astimezone().strftime("%d/%m/%Y %H:%M:%S")


def test_visual_edits_keep_manifest_and_legacy_review_folder(tmp_path):
    folder = tmp_path / "results/etapa7/antigo"
    atomic_json(folder / "plano.json", {"execucoes": [{"id": "s1", "configuracao": "B", "caso": "estavel"}],
                                      "inferencia": {"modelo": "fixture:1"}})
    assert "fixture:1" in session_label({"id": "s1", "configuracao": "B"}, model="fixture:1")
    [record] = list(recordings(tmp_path).values())
    before = (folder / "plano.json").read_bytes()
    legacy_hash = sha256("Etapa 7 · antigo".encode("utf-8")).hexdigest()[:24]
    expected = tmp_path / Path("results/ui/avaliacoes") / legacy_hash
    atomic_json(expected / "avaliacoes/avaliacao.json", {"avaliador": "fixture", "data_utc": "2026-11-28T01:00:00Z",
                "avaliacoes": {"resposta": {"pontuacoes": {"fidelidade_kpm": 2}, "comentario": "Evidência presente"}}})
    save_identity(tmp_path, record, "  Nome visual  ", "Descrição")
    [renamed] = list(recordings(tmp_path).values())
    assert renamed.identity == record.identity and renamed.title == "Nome visual" and renamed.description == "Descrição"
    assert review_folder(tmp_path, renamed)[0] == expected
    assert reviewer_records(tmp_path, renamed, "fixture")["resposta"]["pontuacoes"] == {"fidelidade_kpm": 2}
    assert (folder / "plano.json").read_bytes() == before
    save_identity(tmp_path, renamed, "", "Descrição")
    assert recordings(tmp_path)[record.identity].title == record.automatic_name


def test_duplicates_and_filters_keep_distinct_identities(tmp_path):
    pytest.importorskip("streamlit")
    from oran_lab.ui_history import default_identity, filter_history, selector_labels

    stamp = "2026-11-28T03:00:00+00:00"
    for key in ("a" * 32, "b" * 32):
        operational_record(tmp_path, key, stamp)
    for record in recordings(tmp_path).values():
        save_identity(tmp_path, record, "Ensaio repetido")
    entries = recordings(tmp_path)
    first, second = entries
    assert len(set(selector_labels(entries).values())) == 2
    assert all("Ensaio repetido" not in label for label in selector_labels(entries, blind=True).values())
    assert default_identity(entries, active=second) == second
    assert default_identity(entries, preferred=first, active=second) == first
    record = entries[first]
    assert filter_history(entries, "ENSAIO", source=record.sources[0], model="fixture:1", arch="E",
                          kind="Operacional", state="Concluída", dates=(record.started.astimezone().date(),)) == entries
    assert not filter_history(entries, state="Em execução")
