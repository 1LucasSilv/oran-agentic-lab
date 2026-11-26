"""Planilhas inteiramente sintéticas, criadas em tmp_path e sem acesso à rede."""

from datetime import datetime
from hashlib import sha256
from zipfile import BadZipFile

import pandas as pd
import pytest
from openpyxl import Workbook

from oran_lab.data import load_workbook
from oran_lab.eda import main, time_summary


@pytest.fixture
def synthetic_excel(tmp_path):
    path = tmp_path / "fixture_sintetica.xlsx"
    book = Workbook()
    data = book.active
    data.title = "Medições sintéticas"
    data.append(["Instante", "Leitura", "Rótulo", None])
    data.append([datetime(2025, 1, 1, 12), 7, "NA", None])
    data.append([datetime(2025, 1, 1, 12), 7, "NA", None])
    data.append([datetime(2025, 1, 1, 12, 2), None, "001", 99])
    book.create_sheet("Sem tabela")
    # O nome da aba oficial, sozinho, não identifica o conteúdo.
    other = book.create_sheet("KPM Metrics")
    other.append(["Latency", "Nota"])
    other.append([1234, "sintético"])
    book.save(path)
    return path


def test_reader_preserves_source_and_discovers_sheets(synthetic_excel):
    digest, names, frames = load_workbook(synthetic_excel)
    assert digest == sha256(synthetic_excel.read_bytes()).hexdigest()
    assert names == ["Medições sintéticas", "Sem tabela", "KPM Metrics"]
    frame = frames[names[0]]
    assert frame.columns.tolist() == ["Instante", "Leitura", "Rótulo", "Unnamed: 3"]
    assert frame["Rótulo"].tolist() == ["NA", "NA", "001"]
    assert frame.isna().sum().tolist() == [0, 1, 0, 2]
    assert frame.duplicated().sum() == 1
    assert frames["Sem tabela"].shape == (0, 0)


@pytest.mark.parametrize("mode", ["segundos", "bruto"])
def test_numeric_intervals_keep_row_order_and_gaps(mode):
    series = pd.Series([0, 60, "60", "inválido", 180, None, 120, 0])
    audit = time_summary(series, mode)
    assert audit == {
        "inicio": 0, "fim": 180, "ausentes": 1, "invalidos": 1, "repetidos": 2,
        "recuos": 1, "pares": 3, "min": -120, "mediana": 0, "max": 60,
    }


def test_iso_dates_reject_numeric_indices_and_respect_offsets():
    series = pd.Series(["2025-03-01T01:00:00+01:00", "2025-03-01T00:00:02Z", 123, None])
    audit = time_summary(series, "data")
    assert audit["pares"] == 1
    assert audit["mediana"] == 2
    assert audit["invalidos"] == audit["ausentes"] == 1


def test_unknown_period_with_one_valid_record():
    audit = time_summary(pd.Series(["ruim", "2025-03-01"]), "data")
    assert audit["pares"] == 0
    assert pd.isna(audit["mediana"])


def test_report_and_plots_from_cli(synthetic_excel, tmp_path):
    output = tmp_path / "eda"
    original = synthetic_excel.read_bytes()
    main([str(synthetic_excel), "--saida", str(output)])
    report = (output / "relatorio.md").read_text(encoding="utf-8")
    assert "Linhas integralmente duplicadas após a primeira: 1." in report
    assert "| Leitura | float64 | 1 | 1 | 7 | 7 | 7 | não confirmada |" in report
    assert "| Instante | s |" in report
    assert "| 2 | 0 | 60 | 120 |" in report
    assert "Aba sem tabela de células." in report
    assert "Sem eixo temporal identificado" in report
    assert "Arquivo oficial" not in report
    for number in [1, 3]:
        name = f"aba-{number}.png"
        assert f"({name})" in report
        assert (output / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert not (output / "aba-2.png").exists()
    assert synthetic_excel.read_bytes() == original


def test_cli_selects_sheet_and_configures_raw_axis(synthetic_excel, tmp_path):
    output = tmp_path / "selecao"
    main([str(synthetic_excel), "--saida", str(output), "--aba", "KPM Metrics",
          "--tempo", "KPM Metrics", "Latency", "bruto"])
    report = (output / "relatorio.md").read_text(encoding="utf-8")
    assert "## KPM Metrics" in report
    assert "## Medições sintéticas" not in report
    assert "| Latency | valor bruto | 1234 | 1234 |" in report


@pytest.mark.parametrize("options, message", [
    (["--aba", "Ausente"], "Abas desconhecidas"),
    (["--tempo", "KPM Metrics", "Ausente", "data"], "Eixo temporal ausente"),
    (["--tempo", "KPM Metrics", "Latency", "xyz"], "Modo temporal desconhecido"),
])
def test_bad_configuration(synthetic_excel, tmp_path, capsys, options, message):
    output = tmp_path / "invalido"
    with pytest.raises(SystemExit) as exc:
        main([str(synthetic_excel), "--saida", str(output), *options])
    assert exc.value.code == 2
    assert message in capsys.readouterr().err
    assert not (output / "relatorio.md").exists()


def test_input_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_workbook(tmp_path / "ausente.xlsx")
    with pytest.raises(ValueError, match="xlsx"):
        load_workbook(tmp_path / "dados.csv")
    broken = tmp_path / "invalido.xlsx"
    broken.write_bytes(b"fixture sintetica sem conteudo Excel")
    with pytest.raises(BadZipFile):
        load_workbook(broken)
