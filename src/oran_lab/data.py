"""Leitura de tabelas Excel e descrição do arquivo oficial inspecionado."""

from hashlib import file_digest
from pathlib import Path

import pandas as pd

from .dataset import OFFICIAL_SHA256

KPM = "KPM Metrics"
TRAFFIC = "iperf3 traffic"
OFFICIAL_CLOCKS = {
    KPM: {"Latency": "bruto"},
    TRAFFIC: {"Total time (sec)": "segundos", "Time (sec)": "segundos"},
}
OFFICIAL_UNITS = {
    KPM: {"Register": "índice", "UE.Id": "identificador"},
    TRAFFIC: {
        "Iteration": "índice",
        "Total time (sec)": "s",
        "Time (sec)": "s",
        "Bandwidth (kbps)": "kbps",
        "Iperf bw (kbps)": "kbps",
    },
}


def load_workbook(path: Path, selected: list[str] | None = None):
    """Lê a primeira linha como cabeçalho e preserva todas as colunas com dados."""
    if path.suffix.lower() != ".xlsx":
        raise ValueError("A entrada deve ser um arquivo .xlsx")
    with path.open("rb") as source:
        digest = file_digest(source, "sha256").hexdigest()
        source.seek(0)
        with pd.ExcelFile(source, engine="openpyxl") as book:
            names = book.sheet_names
            missing = set(selected or ()) - set(names)
            if missing:
                raise ValueError(f"Abas desconhecidas {sorted(missing)}. Disponíveis {names}")
            frames = {}
            for name in names:
                if selected is None or name in selected:
                    frame = book.parse(name, dtype=object, keep_default_na=False, na_values=[""])
                    frames[name] = frame.infer_objects()
    return digest, names, frames
