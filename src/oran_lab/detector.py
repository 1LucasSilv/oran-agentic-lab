"""Detector experimental de quedas persistentes de throughput UL."""

import argparse
import json
from bisect import bisect_left
from collections import Counter
from dataclasses import asdict, dataclass
from itertools import groupby
from math import isfinite
from numbers import Real
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from zipfile import BadZipFile

import pandas as pd

from .data import KPM, OFFICIAL_SHA256
from .replay import ReplayConfig, load_kpm, replay

THROUGHPUT = "DRB.UEThpUl"
PRB = "RRU.PrbTotUl"
METRICS = (THROUGHPUT, PRB)

NORMAL = "normal"
SUSPECT = "suspeita"
INSUFFICIENT = "evidencia_insuficiente"


@dataclass(frozen=True)
class DetectorConfig:
    reference_windows: int = 3
    throughput_drop: float = 0.30
    persistence: int = 2
    min_coverage: float = 0.80
    prb_tolerance: float = 0.10

    def __post_init__(self):
        for name, value in (("janelas de referência", self.reference_windows),
                            ("persistência", self.persistence)):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} deve ser um inteiro positivo")
        for name, value in (
            ("queda", self.throughput_drop),
            ("cobertura", self.min_coverage),
            ("tolerância PRB", self.prb_tolerance),
        ):
            if isinstance(value, bool) or not isinstance(value, Real) or not 0 <= value <= 1:
                raise ValueError(f"Fração inválida para {name}")
        if self.throughput_drop == 0 or self.min_coverage == 0:
            raise ValueError("Queda e cobertura devem ser maiores que zero")


@dataclass(frozen=True)
class MetricStats:
    validos: int
    ausentes: int
    invalidos: int
    cobertura: float
    mediana: float | None


def _summarize(series: pd.Series, coverage: float) -> MetricStats:
    present = series.dropna()
    values = [float(value) for value in present
              if isinstance(value, Real) and not isinstance(value, bool)
              and isfinite(value) and value >= 0]
    fraction = len(values) / len(series)
    center = median(values) if values and fraction >= coverage else None
    if center is not None and not isfinite(center):
        center = None
    return MetricStats(len(values), len(series) - len(present),
                       len(present) - len(values), fraction, center)


def _relative(current: float | None, reference: float | None) -> float | None:
    if current is None or reference is None or reference <= 0:
        return None
    change = (current - reference) / reference
    return change if isfinite(change) else None


def _reference_medians(reference: list[dict]) -> dict:
    medians = {}
    for metric in METRICS:
        values = [entry["medianas"][metric] for entry in reference]
        center = median(values) if values and all(value is not None for value in values) else None
        medians[metric] = center if center is not None and isfinite(center) else None
    return medians


def _detect_segment(windows, config: DetectorConfig):
    reference = []
    reference_medians = dict.fromkeys(METRICS)
    history = []
    ends = []
    confirmation_count = 0
    confirmation_end = None
    alert_id = None
    previous_end = None
    parameters = asdict(config)

    for window in windows:
        start, end = window.registers[0], window.registers[-1]
        if previous_end is not None and start > previous_end + 1:
            confirmation_count = 0
            confirmation_end = None
            alert_id = None
        previous_end = end

        stats = {
            metric: _summarize(series, config.min_coverage)
            for metric, series in window.records.reindex(columns=METRICS).items()
        }
        medians = {metric: stat.mediana for metric, stat in stats.items()}
        ue = window.records.get("UE.Id")
        has_ue = ue is not None and ue.notna().all()
        comparable = window.complete and has_ue and medians[THROUGHPUT] is not None
        previous_index = bisect_left(ends, start) - 1
        previous = history[previous_index] if previous_index >= 0 else None
        ready = len(reference) == config.reference_windows
        independent = ready and start > reference[-1]["registros"][-1]
        delta_ref = {metric: _relative(medians[metric], reference_medians[metric])
                     if comparable and independent else None for metric in METRICS}
        delta_prev = {metric: _relative(medians[metric], previous["medianas"][metric])
                      if comparable and previous else None for metric in METRICS}

        descriptor = {"id": window.number, "registros": window.registers, "medianas": medians}
        if comparable:
            history.append(descriptor)
            ends.append(end)

        status, rule, reason = INSUFFICIENT, "janela_incompleta", "Janela parcial; requer uma janela completa."
        if window.complete and not has_ue:
            rule, reason = "ue_ausente", "A janela contém registros sem identificação de UE."
        elif window.complete and not comparable:
            rule, reason = "cobertura_throughput", "Cobertura de throughput UL abaixo do mínimo ou mediana indisponível."
        elif comparable and not ready:
            if not reference or start > reference[-1]["registros"][-1]:
                reference.append(descriptor)
                reference_medians = _reference_medians(reference)
            rule, reason = "formacao_referencia", "Coleta de janelas históricas completas sem sobreposição."
        elif comparable and not independent:
            rule, reason = "sobreposicao_referencia", "A janela compartilha registros com a referência."
        elif comparable and delta_ref[THROUGHPUT] is None:
            rule, reason = "referencia_inutilizavel", "A variação de throughput exige referência positiva e razão finita."
        elif comparable and delta_ref[THROUGHPUT] > -config.throughput_drop:
            status, rule, reason = NORMAL, "queda_abaixo_limiar", "A queda de throughput UL ficou abaixo do limiar."
        elif comparable:
            if confirmation_end is None or start > confirmation_end:
                confirmation_count += 1
                confirmation_end = end
            if confirmation_count < config.persistence:
                rule, reason = "queda_aguarda_persistencia", "A queda atingiu o limiar e aguarda janelas independentes."
            else:
                status, rule = SUSPECT, "queda_persistente_throughput_ul"
                reason = "A queda de throughput UL atingiu o limiar em janelas independentes consecutivas."
                if delta_ref[PRB] is not None and delta_ref[PRB] >= -config.prb_tolerance:
                    rule = "queda_persistente_throughput_ul_com_prb_mantido"
                    reason += " Na janela atual, o PRB UL ficou dentro da tolerância de queda ou aumentou."

        new_alert = status == SUSPECT and alert_id is None
        if new_alert:
            alert_id = f"alerta-{window.number}"
        if status == NORMAL or (status == INSUFFICIENT and rule != "queda_aguarda_persistencia"):
            confirmation_count = 0
            confirmation_end = None
            alert_id = None

        yield {
            "janela": window.identity(),
            "situacao": status,
            "regra": rule,
            "justificativa": reason,
            "parametros": parameters,
            "metricas": {metric: asdict(stat) for metric, stat in stats.items()},
            "referencia": {"janelas": [item["id"] for item in reference], "medianas": reference_medians},
            "janela_anterior_sem_sobreposicao": previous["id"] if previous else None,
            "variacao_relativa_referencia": delta_ref,
            "variacao_relativa_anterior": delta_prev,
            "persistencia_janelas": confirmation_count,
            "alerta_id": alert_id,
            "novo_alerta": new_alert,
        }


def detect(frame: pd.DataFrame, replay_config: ReplayConfig, config: DetectorConfig):
    """Avalia cada janela com histórico do mesmo segmento e de um único UE."""
    if "UE.Id" in frame and frame["UE.Id"].nunique(dropna=True) > 1:
        raise ValueError("O detector espera um único UE por aba; há mais de um UE.Id")
    for _, windows in groupby(replay(frame, replay_config), key=lambda window: window.segment):
        yield from _detect_segment(windows, config)


def _report(result: dict) -> str:
    source = result["fonte"]
    params = result["replay"]
    windows = result["janelas"]
    lines = [
        "# Replay histórico de KPMs", "",
        f"Origem **{source['tipo']}**, arquivo `{source['arquivo']}`, aba `{source['aba']}`.  ",
        f"SHA-256 `{source['sha256']}`.  ",
        f"{result['linhas']} linhas de origem. {len(windows)} janelas emitidas, "
        f"das quais {sum(not item['janela']['completa'] for item in windows)} parciais.",
        "",
        f"Tamanho {params['tamanho']} e avanço {params['avanco']}, ambos em registros.",
        "O eixo de replay é `Register`. A duração física de uma janela permanece indeterminada.",
        "",
    ]
    if not windows:
        lines += ["Nenhuma janela foi emitida com os dados e parâmetros informados.", ""]
    if result["detector"] is not None:
        config = result["detector"]
        counts = Counter(item["situacao"] for item in windows)
        lines += [
            "## Detector de referência", "",
            f"Referência fixa de {config['reference_windows']} janelas históricas independentes por segmento.",
            f"Queda mínima de {config['throughput_drop']:.1%} no throughput UL, "
            f"persistência de {config['persistence']} janelas e cobertura mínima de {config['min_coverage']:.1%}.",
            f"Tolerância de queda de PRB UL de {config['prb_tolerance']:.1%} em relação à sua mediana de referência.",
            "",
            "| Situação | Janelas |",
            "|---|---:|",
            *(f"| {status} | {counts[status]} |" for status in (NORMAL, SUSPECT, INSUFFICIENT)),
            "",
            f"**{len(result['alertas'])} alertas** por início de episódio suspeito.",
            "",
        ]
        for alert in result["alertas"]:
            delta = alert["queda_relativa_throughput_ul"]
            lines.append(f"- `{alert['id']}`, janela {alert['janela_id']}, "
                         f"registros {alert['primeiro_register']}–{alert['ultimo_register']}, "
                         f"queda de {delta:.1%}. {alert['justificativa']}")
        if result["alertas"]:
            lines.append("")
        lines += ["As situações são resultados das regras experimentais. "
                  "Uma avaliação de acurácia ou F1 exige uma referência independente.", ""]
    lines.extend(["Consulte [resultados.json](resultados.json) para os registros de cada janela e suas evidências.", ""])
    return "\n".join(lines)


def run(path: Path, output: Path, sheet: str, replay_config: ReplayConfig,
        config: DetectorConfig | None) -> Path:
    digest, frame = load_kpm(path, sheet)
    windows = ([{"janela": window.identity()} for window in replay(frame, replay_config)]
               if config is None else list(detect(frame, replay_config, config)))
    alerts = []
    for item in windows:
        if item.get("novo_alerta"):
            window = item["janela"]
            alerts.append({
                "id": item["alerta_id"],
                "janela_id": window["id"],
                "primeiro_register": window["registros"][0],
                "ultimo_register": window["registros"][-1],
                "queda_relativa_throughput_ul": -item["variacao_relativa_referencia"][THROUGHPUT],
                "regra": item["regra"],
                "justificativa": item["justificativa"],
            })
    result = {
        "versao_formato": 1,
        "fonte": {
            "tipo": "oai_kpm_oficial" if digest == OFFICIAL_SHA256 else "outro_excel",
            "arquivo": path.name,
            "sha256": digest,
            "aba": sheet,
        },
        "linhas": len(frame),
        "replay": {
            "tamanho": replay_config.size,
            "avanco": replay_config.advance,
            "incluir_incompletas": replay_config.include_partial,
        },
        "detector": asdict(config) if config else None,
        "janelas": windows,
        "alertas": alerts,
    }
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output) as temporary:
        staging = Path(temporary)
        report = staging / "relatorio.md"
        structured = staging / "resultados.json"
        report.write_text(_report(result), encoding="utf-8")
        structured.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
                              encoding="utf-8")
        report.replace(output / report.name)
        structured.replace(output / structured.name)
    return output / report.name


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reproduz janelas de KPMs e aplica o detector de referência.")
    parser.add_argument("excel", type=Path, help="Caminho da planilha .xlsx")
    parser.add_argument("--aba", default=KPM, help="Nome exato da aba de KPMs")
    parser.add_argument("--saida", type=Path, help="Diretório dos resultados")
    parser.add_argument("--tamanho", type=int, default=ReplayConfig.size, help="Registros por janela")
    parser.add_argument("--avanco", type=int, help="Registros entre inícios de janela (padrão: tamanho)")
    parser.add_argument("--descartar-incompletas", action="store_true", help="Omite a janela parcial de cada segmento")
    parser.add_argument("--somente-replay", action="store_true", help="Gera apenas o inventário de janelas")
    parser.add_argument("--referencia", type=int, default=DetectorConfig.reference_windows,
                        help="Janelas independentes para formar a referência")
    parser.add_argument("--queda", type=float, default=DetectorConfig.throughput_drop,
                        help="Fração mínima de queda de throughput UL")
    parser.add_argument("--persistencia", type=int, default=DetectorConfig.persistence,
                        help="Janelas independentes que devem confirmar a queda")
    parser.add_argument("--cobertura", type=float, default=DetectorConfig.min_coverage,
                        help="Fração mínima de valores válidos para calcular a mediana")
    parser.add_argument("--tolerancia-prb", type=float, default=DetectorConfig.prb_tolerance,
                        help="Fração de queda de PRB UL admissível para indicar recursos mantidos")
    args = parser.parse_args(argv)
    try:
        replay_config = ReplayConfig(args.tamanho, args.avanco, not args.descartar_incompletas)
        config = None if args.somente_replay else DetectorConfig(
            args.referencia, args.queda, args.persistencia, args.cobertura, args.tolerancia_prb,
        )
        output = args.saida or Path("results/replay" if args.somente_replay else "results/etapa2")
        report = run(args.excel, output, args.aba, replay_config, config)
    except (ValueError, OSError, BadZipFile) as error:
        parser.exit(2, f"Erro: {error}\n")
    print(report)


if __name__ == "__main__":
    main()
