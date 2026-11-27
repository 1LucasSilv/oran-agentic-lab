"""Testa publicação e preservação usando bytes sintéticos e sem rede."""

from hashlib import sha256
from io import BytesIO

import pytest

from oran_lab import dataset


def test_verified_download_preserves_valid_file(tmp_path, monkeypatch):
    path = tmp_path / "dados históricos" / "planilha.xlsx"
    content = b"fixture sintetica"
    calls = []

    def download(url, *, timeout):
        calls.append(url)
        return BytesIO(content)

    monkeypatch.setattr(dataset, "urlopen", download)
    monkeypatch.setattr(dataset, "OFFICIAL_SHA256", sha256(content).hexdigest())

    with pytest.raises(ValueError, match="ausente"):
        dataset.prepare_dataset(path, check_only=True)
    assert not path.parent.exists()
    assert dataset.prepare_dataset(path)
    assert not dataset.prepare_dataset(path)
    assert not dataset.prepare_dataset(path, check_only=True)
    assert path.read_bytes() == content
    assert calls == [dataset.OFFICIAL_URL]


def test_bad_download_preserves_existing_file_and_cleans_staging(tmp_path, monkeypatch):
    path = tmp_path / "planilha.xlsx"
    path.write_bytes(b"arquivo anterior")
    monkeypatch.setattr(dataset, "urlopen", lambda *args, **kwargs: BytesIO(b"invalido"))

    with pytest.raises(ValueError, match="SHA-256 do download"):
        dataset.prepare_dataset(path)
    assert path.read_bytes() == b"arquivo anterior"
    assert list(tmp_path.iterdir()) == [path]
