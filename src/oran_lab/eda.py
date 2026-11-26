"""Geração de relatório e gráficos exploratórios a partir de um .xlsx."""

import argparse
from datetime import date
from numbers import Integral, Real
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile

import pandas as pd
from matplotlib.figure import Figure
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_numeric_dtype

from .data import KPM, OFFICIAL_CLOCKS, OFFICIAL_SHA256, OFFICIAL_UNITS, TRAFFIC, load_workbook


def number(value):
    if pd.isna(value):
        return "—"
    if isinstance(value, Integral):
        return str(value)
    if isinstance(value, Real):
        if float(value).is_integer():
            return str(int(value))
        return f"{value:.15g}"
    return str(value)


def time_summary(series, mode):
    """Calcula diferenças somente entre linhas vizinhas válidas, na ordem original."""
    if mode == "data":
        # Um inteiro como Register não deve virar nanossegundos desde 1970.
        candidates = series.where(series.map(lambda x: isinstance(x, (str, date))))
        values = pd.to_datetime(candidates, format="ISO8601", errors="coerce", utc=True)
        deltas = values.diff().dt.total_seconds()
    elif mode in ("segundos", "bruto"):
        candidates = series.where(series.map(lambda x: isinstance(x, (str, Real)) and not isinstance(x, bool)))
        values = pd.to_numeric(candidates.astype(object), errors="coerce")
        deltas = values.diff()
    else:
        raise ValueError(f"Modo temporal desconhecido: {mode}")
    valid = values.dropna()
    steps = deltas.dropna()
    return {
        "inicio": valid.min() if len(valid) else None,
        "fim": valid.max() if len(valid) else None,
        "ausentes": int(series.isna().sum()),
        "invalidos": int((series.notna() & values.isna()).sum()),
        "repetidos": int(valid.duplicated().sum()),
        "recuos": int((steps < 0).sum()),
        "pares": len(steps),
        "min": steps.min(),
        "mediana": steps.median(),
        "max": steps.max(),
    }


def table_line(cells):
    return "| " + " | ".join(number(c).replace("|", r"\|").replace("\n", " ") for c in cells) + " |"


def numeric(series):
    return is_numeric_dtype(series) and not is_bool_dtype(series)


def column_table(frame, units):
    lines = [
        "| Coluna | Tipo inferido | Ausentes | Distintos presentes | Mínimo | Mediana | Máximo | Unidade ou papel |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for name, series in frame.items():
        bounds = (series.min(), series.median(), series.max()) if numeric(series) else (None,) * 3
        lines.append(table_line([name, series.dtype, series.isna().sum(), series.nunique(),
                                 *bounds, units.get(name, "não confirmada")]))
    return lines


def time_table(frame, clocks):
    if not clocks:
        return ["Sem eixo temporal identificado. A periodicidade física fica indeterminada."]
    lines = [
        "Diferenças entre linhas consecutivas na ordem do arquivo, incluindo recuos e empates.",
        "",
        "| Coluna | Unidade do Δ | Valor mínimo | Valor máximo | Ausentes | Inválidos | Repetições após a primeira | Recuos | Pares válidos | Δ mín. | Δ mediano | Δ máx. |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, mode in clocks.items():
        info = time_summary(frame[name], mode)
        unit = "valor bruto" if mode == "bruto" else "s"
        lines.append(table_line([name, unit, *info.values()]))
    return lines


def plot_sheet(frame, name, official, target):
    metrics = [c for c in frame if numeric(frame[c]) and frame[c].notna().any()]
    x, label = range(1, len(frame) + 1), "Posição da linha de dados"
    if official and name == KPM:
        metrics = [c for c in metrics if c.startswith(("RRU.", "DRB."))]
        x, label = frame["Register"], "Register (índice)"
    if official and name == TRAFFIC:
        metrics = ["Bandwidth (kbps)", "Iperf bw (kbps)"]
        x, label = frame["Total time (sec)"], "Tempo total (s)"
    if not metrics:
        return False
    figure = Figure(figsize=(9, 2 * len(metrics) + 0.6), layout="constrained")
    axes = figure.subplots(len(metrics), 1, sharex=True, squeeze=False)[:, 0]
    for axis, metric in zip(axes, metrics):
        axis.plot(x, frame[metric], linewidth=0.8, marker=".", markersize=2, color="#146777")
        axis.set_title(str(metric), loc="left", fontsize=10)
        axis.grid(axis="y", alpha=0.25)
    axes[-1].set_xlabel(label)
    figure.suptitle(name)
    figure.savefig(target, dpi=120)
    return True


def generate(path: Path, output: Path, sheets=None, times=()):
    digest, names, frames = load_workbook(path, sheets)
    official = digest == OFFICIAL_SHA256
    clocks = {}
    for name, frame in frames.items():
        clocks[name] = {c: "data" for c in frame if is_datetime64_any_dtype(frame[c])}
        if official:
            clocks[name].update(OFFICIAL_CLOCKS.get(name, {}))
    for name, column, mode in times:
        if name not in frames or column not in frames[name]:
            raise ValueError(f"Eixo temporal ausente nas tabelas selecionadas: {name} / {column}")
        clocks[name][column] = mode

    lines = [
        "# Auditoria exploratória do Excel", "",
        f"Arquivo: `{path.name}`  ", f"SHA-256: `{digest}`  ",
        f"Abas no arquivo: {', '.join(names)}.", "",
    ]
    if official:
        lines += ["Arquivo oficial da revisão `328ab90c9faabbba6a036255ac503683c227fa34`.",
                  "A planilha fornece tempos relativos para o tráfego. A unidade e a origem de "
                  "`Latency` precisam de confirmação para alinhar as duas tabelas. "
                  "Os gráficos usam os eixos próprios de cada aba.", ""]
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output) as folder:
        staging = Path(folder)
        for name, frame in frames.items():
            lines += [f"## {name}", "",
                      f"{len(frame)} linhas de dados, {len(frame.columns)} colunas. "
                      f"Linhas integralmente duplicadas após a primeira: {frame.duplicated().sum()}.", ""]
            if len(frame.columns) == 0:
                lines += ["Aba sem tabela de células.", ""]
                continue
            units = OFFICIAL_UNITS.get(name, {}) if official else {}
            lines += column_table(frame, units) + [""] + time_table(frame, clocks[name]) + [""]
            filename = f"aba-{names.index(name) + 1}.png"
            if plot_sheet(frame, name, official, staging / filename):
                lines += [f"![Séries da aba {name}]({filename})", ""]
        report = "relatorio.md"
        (staging / report).write_text("\n".join(lines), encoding="utf-8")
        for plot in staging.glob("*.png"):
            plot.replace(output / plot.name)
        (staging / report).replace(output / report)
    return output / report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("excel", type=Path, help="Caminho do arquivo .xlsx")
    parser.add_argument("--saida", type=Path, default=Path("results/eda"))
    parser.add_argument("--aba", action="append", help="Nome exato. Repita para selecionar várias.")
    parser.add_argument("--tempo", nargs=3, action="append", default=[], metavar=("ABA", "COLUNA", "MODO"),
                        help="Eixo temporal adicional ou substituto. Modos: data (ISO/Excel), segundos, bruto.")
    args = parser.parse_args(argv)
    try:
        report = generate(args.excel, args.saida, args.aba, args.tempo)
    except (ValueError, OSError, BadZipFile) as error:
        parser.exit(2, f"Erro: {error}\n")
    print(report)


if __name__ == "__main__":
    main()
