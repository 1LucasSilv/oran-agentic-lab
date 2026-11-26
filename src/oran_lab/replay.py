"""Replay histórico por posição na planilha e sequência de Register."""

from collections.abc import Iterator
from dataclasses import dataclass
from numbers import Integral, Real
from pathlib import Path

import pandas as pd

from .data import KPM, load_workbook


@dataclass(frozen=True)
class ReplayConfig:
    size: int = 30
    stride: int | None = None
    include_partial: bool = True

    def __post_init__(self):
        for name, value in (("tamanho", self.size), ("avanço", self.advance)):
            if type(value) is not int or value < 1:
                raise ValueError(f"O {name} da janela deve ser um inteiro positivo")

    @property
    def advance(self) -> int:
        return self.size if self.stride is None else self.stride


@dataclass(frozen=True)
class Window:
    number: int
    segment: int
    registers: tuple[int, ...]
    first_excel_row: int
    complete: bool
    records: pd.DataFrame

    def identity(self) -> dict:
        return {
            "id": self.number,
            "segmento": self.segment,
            "registros": self.registers,
            "primeira_linha_excel": self.first_excel_row,
            "ultima_linha_excel": self.first_excel_row + len(self.registers) - 1,
            "completa": self.complete,
        }


def load_kpm(path: Path, sheet: str = KPM) -> tuple[str, pd.DataFrame]:
    digest, _, sheets = load_workbook(path, [sheet])
    return digest, sheets[sheet]


def validated_registers(frame: pd.DataFrame) -> list[int]:
    """Retorna os identificadores na ordem de origem após verificar a sequência."""
    if len(frame) == 0:
        return []
    if "Register" not in frame.columns:
        raise ValueError("Coluna Register ausente na aba selecionada")
    registers = []
    for row, value in enumerate(frame["Register"], start=2):
        # Excel pode devolver um inteiro como float quando há células vazias.
        integer = isinstance(value, Integral) or (
            isinstance(value, Real) and float(value).is_integer()
        )
        if isinstance(value, bool) or not integer or value < 1:
            raise ValueError(f"Register deve ser um inteiro positivo na linha Excel {row}")
        current = int(value)
        if registers and current <= registers[-1]:
            raise ValueError(f"Register duplicado ou fora de ordem na linha Excel {row}")
        registers.append(current)
    return registers


def replay(frame: pd.DataFrame, config: ReplayConfig = ReplayConfig()) -> Iterator[Window]:
    """Emite janelas na ordem original, sem atravessar lacunas de Register."""
    registers = validated_registers(frame)
    boundaries = [0]
    boundaries.extend(i for i in range(1, len(registers)) if registers[i] != registers[i - 1] + 1)
    boundaries.append(len(registers))
    number = 0
    for segment, (begin, end) in enumerate(zip(boundaries, boundaries[1:]), start=1):
        for start in range(begin, end, config.advance):
            stop = min(start + config.size, end)
            complete = stop - start == config.size
            if complete or config.include_partial:
                number += 1
                yield Window(number, segment, tuple(registers[start:stop]), start + 2,
                             complete, frame.iloc[start:stop].copy())
            if stop == end:
                break
