"""Cenários sintéticos com níveis e resultados esperados definidos no teste."""

import json

import pandas as pd
import pytest
from openpyxl import Workbook

from oran_lab.detector import INSUFFICIENT, NORMAL, PRB, SUSPECT, THROUGHPUT, DetectorConfig, detect, main
from oran_lab.replay import ReplayConfig, load_kpm, replay


@pytest.fixture
def synthetic_frame():
    def make(throughput, prb=None, registers=None):
        return pd.DataFrame({
            "Register": range(1, len(throughput) + 1) if registers is None else registers,
            "UE.Id": 1,
            THROUGHPUT: throughput,
            PRB: [1000] * len(throughput) if prb is None else prb,
            "Latency": list(reversed(range(len(throughput)))),
        })

    return make


@pytest.fixture
def synthetic_excel(tmp_path):
    path = tmp_path / "fixture_sintetica_etapa2.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "KPM sintético"
    sheet.append(["Register", "UE.Id", THROUGHPUT, PRB])
    for register, value in enumerate([100, 100, 60, 60, 60, 60, 100], start=1):
        sheet.append([register, 1, value, 1000])
    book.create_sheet("Aba vazia")
    book.create_sheet("Só cabeçalho").append(["Register", "UE.Id"])
    book.save(path)
    return path


def test_replay_preserves_registers_and_rows_across_missing_records(synthetic_frame):
    frame = synthetic_frame([80, 70, 60, 55, 45, 35], registers=[8, 9, 10, 14, 15, 16])
    windows = list(replay(frame, ReplayConfig(size=2)))
    assert [window.registers for window in windows] == [(8, 9), (10,), (14, 15), (16,)]
    assert [window.segment for window in windows] == [1, 1, 2, 2]
    assert [window.first_excel_row for window in windows] == [2, 4, 5, 7]
    assert [window.complete for window in windows] == [True, False, True, False]
    assert windows[0].records[THROUGHPUT].tolist() == [80, 70]
    windows[0].records.loc[0, THROUGHPUT] = 1
    assert frame.loc[0, THROUGHPUT] == 80


@pytest.mark.parametrize("stride, partial, expected", [
    (2, True, [(1, 2, 3, 4), (3, 4, 5, 6), (5, 6, 7)]),
    (2, False, [(1, 2, 3, 4), (3, 4, 5, 6)]),
    (4, True, [(1, 2, 3, 4), (5, 6, 7)]),
    (5, True, [(1, 2, 3, 4), (6, 7)]),
    (1, True, [(1, 2, 3, 4), (2, 3, 4, 5), (3, 4, 5, 6), (4, 5, 6, 7)]),
])
def test_stride_and_only_one_partial_tail(synthetic_frame, stride, partial, expected):
    frame = synthetic_frame([1] * 7)
    assert [w.registers for w in replay(frame, ReplayConfig(4, stride, partial))] == expected


@pytest.mark.parametrize("values", [[1, None], [1, 1], [2, 1], [0, 1], [1, 2.5], ["1", "2"], [True, 2]])
def test_invalid_register_is_rejected_instead_of_sorted_or_imputed(synthetic_frame, values):
    with pytest.raises(ValueError, match="Register.*linha Excel"):
        list(replay(synthetic_frame([1, 2], registers=values)))


def test_empty_and_nonempty_sheet_without_register(synthetic_excel):
    for name in ("Aba vazia", "Só cabeçalho"):
        _, frame = load_kpm(synthetic_excel, name)
        assert list(replay(frame)) == []
        assert list(detect(frame, ReplayConfig(), DetectorConfig())) == []
    with pytest.raises(ValueError, match="Register ausente"):
        list(replay(pd.DataFrame({"UE.Id": [1]})))


@pytest.mark.parametrize("params", [{"size": 0}, {"stride": -1}, {"size": True}, {"stride": 1.5}])
def test_invalid_replay_parameters(params):
    with pytest.raises(ValueError):
        ReplayConfig(**params)


@pytest.mark.parametrize("params", [
    {"reference_windows": 0}, {"persistence": 0}, {"throughput_drop": 1.1},
    {"min_coverage": 0}, {"min_coverage": float("nan")}, {"prb_tolerance": -0.1},
])
def test_invalid_detector_parameters(params):
    with pytest.raises(ValueError):
        DetectorConfig(**params)


def test_fixed_reference_persistence_prb_context_and_alert_deduplication(synthetic_frame):
    # Níveis por janela de 2 registros. 70/100 está exatamente no limiar de queda.
    frame = synthetic_frame(
        [100]*2 + [70]*2 + [60]*2 + [60]*2 + [100]*2 + [60]*4,
        prb=[1000]*4 + [900]*2 + [800]*2 + [1000]*6,
    )
    results = list(detect(frame, ReplayConfig(2), DetectorConfig(reference_windows=1)))
    assert [r["situacao"] for r in results] == [
        INSUFFICIENT, INSUFFICIENT, SUSPECT, SUSPECT, NORMAL, INSUFFICIENT, SUSPECT,
    ]
    assert [r["janela"]["id"] for r in results if r["novo_alerta"]] == [3, 7]
    assert results[2]["alerta_id"] == results[3]["alerta_id"] == "alerta-3"
    assert results[2]["regra"] == "queda_persistente_throughput_ul_com_prb_mantido"
    assert results[3]["regra"] == "queda_persistente_throughput_ul"
    assert results[2]["referencia"] == {"janelas": [1], "medianas": {THROUGHPUT: 100, PRB: 1000}}
    assert results[2]["variacao_relativa_referencia"] == {THROUGHPUT: -0.4, PRB: -0.1}
    assert results[2]["janela_anterior_sem_sobreposicao"] == 2
    assert results[2]["variacao_relativa_anterior"][THROUGHPUT] == pytest.approx(-1 / 7)


def test_overlapping_candidates_require_new_records_and_do_not_leak_from_reference(synthetic_frame):
    frame = synthetic_frame([100] * 4 + [50] * 10)
    results = list(detect(frame, ReplayConfig(4, 2), DetectorConfig(reference_windows=1)))
    assert [r["regra"] for r in results[:4]] == [
        "formacao_referencia", "sobreposicao_referencia",
        "queda_aguarda_persistencia", "queda_aguarda_persistencia",
    ]
    assert [r["persistencia_janelas"] for r in results] == [0, 0, 1, 1, 2, 2]
    assert [r["janela"]["registros"][0] for r in results if r["novo_alerta"]] == [9]


def test_reference_is_median_of_preceding_windows_and_parameter_changes_outcome(synthetic_frame):
    frame = synthetic_frame([80]*2 + [140]*2 + [100]*2 + [75]*4)
    params = ReplayConfig(2)
    reference = list(detect(frame, params, DetectorConfig()))
    changed = list(detect(frame, params, DetectorConfig(throughput_drop=.25, persistence=1)))
    assert reference[-1]["referencia"]["medianas"][THROUGHPUT] == 100
    assert reference[-1]["situacao"] == NORMAL
    assert changed[3]["novo_alerta"]
    assert changed[3]["parametros"]["throughput_drop"] == .25
    assert list(detect(frame.iloc[:8], params, DetectorConfig())) == reference[:4]


def test_coverage_and_invalid_metrics_interrupt_persistence(synthetic_frame):
    frame = synthetic_frame([100]*4 + [50]*4 + [None, "texto", -1, float("inf")] + [50]*8,
                            prb=[None]*20)
    config = DetectorConfig(reference_windows=1, min_coverage=.75)
    results = list(detect(frame, ReplayConfig(4), config))
    assert results[2]["regra"] == "cobertura_throughput"
    assert results[2]["metricas"][THROUGHPUT] == {
        "validos": 0, "ausentes": 1, "invalidos": 3, "cobertura": 0, "mediana": None,
    }
    assert results[3]["regra"] == "queda_aguarda_persistencia"
    assert results[4]["regra"] == "queda_persistente_throughput_ul"


def test_coverage_equal_to_minimum_and_prb_missing_are_usable(synthetic_frame):
    frame = synthetic_frame([100, 100, 100, None, 50, 50, 50, None]).drop(columns=PRB)
    params = ReplayConfig(4)
    config = DetectorConfig(reference_windows=1, persistence=1, min_coverage=.75)
    result = list(detect(frame, params, config))[-1]
    assert result["situacao"] == SUSPECT
    assert result["metricas"][PRB]["ausentes"] == 4
    assert result["variacao_relativa_referencia"][PRB] is None


def test_gap_resets_reference_and_zero_baseline_has_no_relative_change(synthetic_frame):
    frame = synthetic_frame([100, 100, 50, 50, 0, 0, 0, 0, 1],
                            registers=[1, 2, 3, 4, 8, 9, 10, 11, 12])
    results = list(detect(frame, ReplayConfig(2), DetectorConfig(reference_windows=1)))
    assert [r["regra"] for r in results] == [
        "formacao_referencia", "queda_aguarda_persistencia", "formacao_referencia",
        "referencia_inutilizavel", "janela_incompleta",
    ]
    assert results[2]["referencia"]["janelas"] == [3]
    assert results[2]["janela_anterior_sem_sobreposicao"] is None
    assert not any(item["novo_alerta"] for item in results)


def test_sampling_with_gaps_between_windows_cannot_confirm_persistence(synthetic_frame):
    frame = synthetic_frame([100] * 2 + [50] * 10)
    results = list(detect(frame, ReplayConfig(2, 3), DetectorConfig(reference_windows=1)))
    assert [r["persistencia_janelas"] for r in results] == [0, 1, 1, 1]
    assert all(r["situacao"] == INSUFFICIENT for r in results)


def test_ue_identification_is_required_for_detection(synthetic_frame):
    frame = synthetic_frame([100, 100, 50, 50])
    frame["UE.Id"] = [1, None, 1, 1]
    replay_config = ReplayConfig(2)
    config = DetectorConfig(reference_windows=1)
    assert list(detect(frame, replay_config, config))[0]["regra"] == "ue_ausente"
    frame.loc[1, "UE.Id"] = 2
    with pytest.raises(ValueError, match="único UE"):
        list(detect(frame, replay_config, config))


def test_cli_is_reproducible_and_preserves_synthetic_excel(synthetic_excel, tmp_path):
    original = synthetic_excel.read_bytes()
    folders = [tmp_path / "primeira", tmp_path / "segunda"]
    for output in folders:
        main([str(synthetic_excel), "--aba", "KPM sintético", "--saida", str(output),
              "--tamanho", "2", "--referencia", "1"])
    for name in ("resultados.json", "relatorio.md"):
        assert (folders[0] / name).read_bytes() == (folders[1] / name).read_bytes()
    result = json.loads((folders[0] / "resultados.json").read_text(encoding="utf-8"))
    assert result["fonte"]["tipo"] == "outro_excel"
    assert result["janelas"][2]["janela"]["registros"] == [5, 6]
    assert len(result["alertas"]) == 1
    assert result["alertas"][0]["janela_id"] == 3
    assert synthetic_excel.read_bytes() == original


def test_cli_empty_and_replay_only(synthetic_excel, tmp_path):
    main([str(synthetic_excel), "--aba", "Aba vazia", "--somente-replay", "--saida", str(tmp_path)])
    result = json.loads((tmp_path / "resultados.json").read_text(encoding="utf-8"))
    assert result["linhas"] == 0
    assert result["janelas"] == []
    assert result["detector"] is None
    assert "Nenhuma janela" in (tmp_path / "relatorio.md").read_text(encoding="utf-8")


def test_cli_rejects_invalid_input_without_creating_output(synthetic_excel, tmp_path, capsys):
    output = tmp_path / "invalido"
    with pytest.raises(SystemExit) as error:
        main([str(synthetic_excel), "--aba", "Aba inexistente", "--saida", str(output)])
    assert error.value.code == 2
    assert "Abas desconhecidas" in capsys.readouterr().err
    assert not output.exists()
