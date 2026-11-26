"""Loop determinístico sobre resultados do detector e demonstração local."""

import argparse
import json
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile

import pandas as pd

from .data import KPM, OFFICIAL_SHA256
from .detector import INSUFFICIENT, NORMAL, PRB, SUSPECT, THROUGHPUT, DetectorConfig, detect
from .replay import ReplayConfig, load_kpm
from .simulator import EXPAND, INTENSIFY, NO_ACTION, PRIORITIZE, REGISTER_ALERT, Limits, Simulator


def propose(detection: dict) -> dict:
    """Política de referência para uma janela já avaliada pelo detector."""
    if detection["situacao"] == SUSPECT and detection["novo_alerta"]:
        return {
            "acao": REGISTER_ALERT,
            "parametros": {"evento_id": detection["alerta_id"]},
            "justificativa": detection["justificativa"],
        }
    reasons = {
        NORMAL: "A janela ficou abaixo do limiar experimental.",
        INSUFFICIENT: "Evidência insuficiente. " + detection["justificativa"],
        SUSPECT: "Episódio suspeito já identificado pelo detector.",
    }
    return {"acao": NO_ACTION, "parametros": {}, "justificativa": reasons[detection["situacao"]]}


def _synthetic_frame() -> tuple[pd.DataFrame, dict]:
    levels = [100] * 6 + [50] * 6 + [100] * 4
    rows = [
        {"Register": register, "UE.Id": 1, THROUGHPUT: level, PRB: 1000}
        for register, level in enumerate(levels, start=1)
    ]
    content = json.dumps(rows, sort_keys=True).encode("utf-8")
    return pd.DataFrame(rows), {
        "tipo": "sintetico", "cenario": "queda_ul_persistente_v1",
        "sha256": sha256(content).hexdigest(), "hash_de": "registros JSON canônicos",
    }


def _controlled_actions(simulator: Simulator):
    # Âncora definida pelo cenário. Se a detecção mudar, as recusas ficam visíveis no relatório.
    event_id, window_id = "alerta-5", 5
    for action, params, reason in (
        (REGISTER_ALERT, {}, "Tentativa controlada de duplicar o alerta"),
        (PRIORITIZE, {"prioridade": "alta"}, "Priorizar investigação no cenário controlado"),
        (EXPAND, {"tamanho_registros": 5}, "Consultar três registros anteriores ao contexto inicial"),
        (EXPAND, {"tamanho_registros": 121}, "Testar recusa por excesso de tamanho"),
        (INTENSIFY, {"avanco_registros": 1}, "Reduzir o avanço configurado para inspeções futuras"),
    ):
        simulator.apply(
            {"acao": action, "parametros": {"evento_id": event_id, **params}, "justificativa": reason},
            window_id=window_id, origin="cenario_controlado",
        )


def run_loop(frame: pd.DataFrame, source: dict, replay_config: ReplayConfig = ReplayConfig(),
             detector_config: DetectorConfig = DetectorConfig(), limits: Limits = Limits(),
             *, controlled: bool = False) -> dict:
    """Executa o detector, aplica a política e devolve a trilha e o estado serializáveis."""
    detections = list(detect(frame, replay_config, detector_config))
    simulator = Simulator(frame, detections, replay_config.advance, limits)
    initial = simulator.state()
    for detection in detections:
        simulator.apply(propose(detection), window_id=detection["janela"]["id"],
                        origin="politica_deterministica")
    if controlled:
        _controlled_actions(simulator)
    return {
        "versao_formato": 1,
        "fonte": source,
        "linhas": len(frame),
        "replay": {
            "tamanho": replay_config.size,
            "avanco": replay_config.advance,
            "incluir_incompletas": replay_config.include_partial,
        },
        "detector": asdict(detector_config),
        "limites": asdict(limits),
        "deteccoes": detections,
        "simulador": {
            "estado_inicial": initial, "estado_final": simulator.state(), "historico": simulator.history(),
        },
    }


def _report(result: dict) -> str:
    source = result["fonte"]
    simulator = result["simulador"]
    state = simulator["estado_final"]
    history = simulator["historico"]
    detections = Counter(item["situacao"] for item in result["deteccoes"])
    decisions = Counter(item["validacao"]["estado"] for item in history)
    executions = Counter(item["execucao"]["estado"] for item in history)
    name = source.get("arquivo", source.get("cenario"))
    lines = [
        "# Loop de ação simulada", "",
        f"Origem **{source['tipo']}** · `{name}`.",
        f"SHA-256 `{source['sha256']}`.",
        f"{result['linhas']} registros históricos e {len(result['deteccoes'])} janelas avaliadas.", "",
        "| Situação do detector | Janelas |", "|---|---:|",
        *(f"| {status} | {detections[status]} |" for status in (NORMAL, SUSPECT, INSUFFICIENT)),
        "",
        f"Propostas aceitas **{decisions['aceita']}**, recusadas **{decisions['recusada']}**.",
        f"Execuções **{executions['executada']}**, propostas sem execução **{executions['nao_executada']}**, "
        f"falhas **{executions['falha']}**.", "",
        f"Alertas registrados **{len(state['alertas'])}**.",
        f"Registros adicionais consultados **{state['analise']['registros_adicionais_consultados']}**.",
        f"Avanço de inspeção **{simulator['estado_inicial']['inspecao']['avanco_registros']} → "
        f"{state['inspecao']['avanco_registros']} registros**.", "",
    ]
    highlighted = [item for item in history if item["validacao"]["estado"] == "recusada"
                   or item["execucao"]["estado"] != "nao_executada"]
    if highlighted:
        lines += ["## Ações que alteraram o estado, recusas e falhas", ""]
        for item in highlighted:
            outcome = (item["validacao"] if item["validacao"]["estado"] == "recusada" else item["execucao"])
            lines.append(f"- Decisão {item['id']} · `{item['proposta']['acao']}` · **{outcome['estado']}**. "
                         f"{outcome['justificativa']}.")
        lines.append("")
    lines.extend([
        "As alterações registradas são efeitos locais do simulador sobre alertas, prioridades e inspeção "
        "de dados históricos. A duração física das janelas permanece indeterminada.", "",
        "O [JSON de resultados](resultados.json) contém as evidências e a comparação antes/depois de cada proposta.",
        "",
    ])
    return "\n".join(lines)


def write_results(result: dict, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output) as folder:
        report = Path(folder) / "relatorio.md"
        structured = report.with_name("resultados.json")
        report.write_text(_report(result), encoding="utf-8")
        structured.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
                              encoding="utf-8")
        report.replace(output / report.name)
        structured.replace(output / structured.name)
    return output / report.name


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("excel", type=Path, nargs="?", help="Planilha .xlsx da série histórica")
    parser.add_argument("--sintetico", action="store_true", help="Executa a queda sintética e as ações controladas")
    parser.add_argument("--aba", default=KPM)
    parser.add_argument("--saida", type=Path)
    parser.add_argument("--tamanho", type=int, help="Registros por janela na execução com Excel")
    parser.add_argument("--avanco", type=int, help="Registros entre janelas na execução com Excel")
    args = parser.parse_args(argv)
    if (args.excel is not None) == args.sintetico:
        parser.error("Informe o Excel ou use --sintetico")
    if args.sintetico and (args.tamanho is not None or args.avanco is not None):
        parser.error("O cenário sintético usa janelas fixas de 2 registros")
    try:
        if args.sintetico:
            frame, source = _synthetic_frame()
            config = ReplayConfig(size=2)
            subdir = "sintetico"
        else:
            digest, frame = load_kpm(args.excel, args.aba)
            official = digest == OFFICIAL_SHA256
            source = {
                "tipo": "oai_kpm_oficial" if official else "outro_excel",
                "arquivo": args.excel.name, "aba": args.aba, "sha256": digest,
            }
            size = ReplayConfig.size if args.tamanho is None else args.tamanho
            config = ReplayConfig(size=size, stride=args.avanco)
            subdir = "oficial" if official else "outro_excel"
        result = run_loop(frame, source, config, controlled=args.sintetico)
        report = write_results(result, args.saida or Path("results/etapa3") / subdir)
    except (ValueError, OSError, BadZipFile) as error:
        parser.exit(2, f"Erro: {error}\n")
    print(report)


if __name__ == "__main__":
    main()
