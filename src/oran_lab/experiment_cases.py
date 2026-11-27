"""Casos pré-especificados da Etapa 7, independentes das respostas dos modelos."""

from dataclasses import dataclass

import pandas as pd

from .data import OFFICIAL_SHA256
from .detector import INSUFFICIENT, NORMAL, PRB, SUSPECT, THROUGHPUT, DetectorConfig, detect
from .rag import digest_json
from .replay import ReplayConfig, load_kpm
from .simulator import NO_ACTION, REGISTER_ALERT, Limits

DETECTOR = DetectorConfig()
LIMITS = Limits()
I, N, S = INSUFFICIENT, NORMAL, SUSPECT


@dataclass(frozen=True)
class Case:
    id: str
    phase: str
    records: tuple
    replay: ReplayConfig
    targets: tuple[int, ...]
    expectations: tuple
    rationale: str
    source_sha256: str | None = None

    def frame(self, target=None):
        rows = self.records if target is None else self.records[:target * self.replay.size]
        return pd.DataFrame(rows, columns=["Register", "UE.Id", THROUGHPUT, PRB])

    def expectation(self, window):
        for number, status, action in self.expectations:
            if number == window:
                params = {"evento_id": f"alerta-{number}"} if action == REGISTER_ALERT else {}
                return {"situacao": status, "acao": action, "parametros": params}
        return None

    def manifest(self):
        return {
            "id": self.id, "fase": self.phase, "fonte_sha256": self.source_sha256,
            "linhas": len(self.records), "alvos": list(self.targets), "motivo": self.rationale,
            "replay": {"size": self.replay.size, "stride": self.replay.advance},
            "expectativas": {str(k): self.expectation(k) for k, _, _ in self.expectations},
            "serie_sha256": digest_json(self.records),
            "serie": [list(row) for row in self.records] if self.source_sha256 is None else None,
        }


def synthetic(name, phase, throughput, prb, target, statuses, rationale):
    rows = tuple((i * 3 + j + 1, 1, ul, blocks)
                 for i, (ul, blocks) in enumerate(zip(throughput, prb, strict=True)) for j in range(3))
    expectations = tuple((i + 1, status, REGISTER_ALERT if status == S and statuses[i - 1] != S else NO_ACTION)
                         for i, status in enumerate(statuses))
    return Case(name, phase, rows, ReplayConfig(3), (target,), expectations, rationale)


FINAL_CASES = (
    synthetic("estavel", "final", (95, 100, 105, 98, 101, 99), (80, 82, 81, 82, 80, 81),
              5, (I, I, I, N, N, N), "Variação moderada dentro da referência. Nenhuma ação no alvo."),
    synthetic("queda-isolada", "final", (114, 120, 126, 60, 116, 120), (90, 90, 90, 90, 90, 90),
              4, (I, I, I, I, N, N), "Uma queda independente ainda não satisfaz a persistência."),
    synthetic("queda-persistente", "final", (190, 200, 210, 112, 106, 103), (150, 146, 148, 147, 149, 148),
              5, (I, I, I, I, S, S), "Duas quedas com PRB mantido justificam registrar o episódio heurístico."),
    synthetic("queda-ul-prb", "final", (140, 150, 160, 82, 79, 76), (120, 123, 117, 60, 57, 55),
              5, (I, I, I, I, S, S), "A queda conjunta ainda dispara a heurística de throughput. A causa permanece aberta."),
    synthetic("recuperacao", "final", (105, 110, 115, 58, 55, 108), (75, 74, 76, 77, 75, 74),
              6, (I, I, I, I, S, N), "Após o episódio, a janela-alvo voltou à referência. O alerta anterior fica no histórico."),
    synthetic("insuficiente", "final", (125, 130, 135, 129, None, 131), (102, 100, 98, 100, 98, 101),
              5, (I, I, I, N, I, N), "O throughput UL ausente no alvo impede uma inferência operacional."),
)
PILOT_CASES = (
    synthetic("piloto-episodio", "piloto", (260, 270, 280, 149, 141, 136), (200, 201, 202, 200, 199, 200),
              5, (I, I, I, I, S, S), "Verifica o fluxo de registro de alerta com evidência persistente."),
    synthetic("piloto-sem-evidencia", "piloto", (310, 320, 330, None, 318, 325), (210, 210, 211, 210, 209, 210),
              4, (I, I, I, I, N, N), "Verifica abstinência com throughput ausente e PRB presente."),
)


def official_case(path):
    digest, frame = load_kpm(path)
    if digest != OFFICIAL_SHA256:
        raise ValueError("A exploração requer o Excel oficial com SHA-256 auditado")
    columns = ["Register", "UE.Id", THROUGHPUT, PRB]
    # Janelas 1 e 4 fixadas após inspeção do replay, antes de qualquer inferência.
    rows = frame.loc[:, columns].iloc[:120].astype(object)
    records = tuple(tuple(row) for row in rows.where(rows.notna(), None).itertuples(index=False, name=None))
    return Case("excel-oficial", "exploratorio", records, ReplayConfig(), (1, 4),
                ((1, I, NO_ACTION), (4, N, NO_ACTION)),
                "Formação de referência (Register 1–30) e primeira janela normal (91–120). "
                "Classificação heurística, sem rótulos de falha real.", digest)


def case_catalog(phase, excel=None):
    if phase == "final":
        return FINAL_CASES
    if phase == "piloto":
        return PILOT_CASES
    if phase == "exploratorio" and excel is not None:
        return (official_case(excel),)
    raise ValueError("Use piloto, final ou exploratorio com o Excel oficial")


def detections_for(case, target=None):
    frame = case.frame(target)
    detections = list(detect(frame, case.replay, DETECTOR))
    for item in detections:
        number = item["janela"]["id"]
        expected = case.expectation(number)
        if expected and item["situacao"] != expected["situacao"]:
            raise ValueError(f"Detecção diverge da expectativa pré-fixada em {case.id}/{number}")
    return frame, detections
