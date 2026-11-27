"""Identidade, verificação e download da revisão auditada do dataset oficial."""

import shutil
from hashlib import file_digest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote
from urllib.request import urlopen

OFFICIAL_REVISION = "328ab90c9faabbba6a036255ac503683c227fa34"
OFFICIAL_FILENAME = "20250321_11.17.57_KPM_vs_iper3_1000ms_05_weeks(2).xlsx"
OFFICIAL_URL = (
    "https://raw.githubusercontent.com/CTTCADAPTRU/OAI-KPM-dataset/"
    f"{OFFICIAL_REVISION}/{quote(OFFICIAL_FILENAME)}"
)
OFFICIAL_SHA256 = "d570d8c0567b7ec85fd5e3ca865d1cc109dc741583b01d3ee4f1ff964892d30c"
OFFICIAL_PATH = Path("data", "raw", OFFICIAL_FILENAME)


def dataset_digest(path: Path) -> str:
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def prepare_dataset(path: Path, *, check_only: bool = False) -> bool:
    """Retorna True se publicou um download ou False se preservou a cópia válida."""
    if path.is_file() and dataset_digest(path) == OFFICIAL_SHA256:
        return False
    if check_only:
        raise ValueError("Arquivo ausente ou SHA-256 diferente da revisão auditada")

    path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=path.parent) as folder:
        staged = Path(folder) / path.name
        with urlopen(OFFICIAL_URL, timeout=30) as response, staged.open("wb") as output:
            shutil.copyfileobj(response, output)
        if dataset_digest(staged) != OFFICIAL_SHA256:
            raise ValueError("SHA-256 do download diferente da revisão auditada")
        if path.is_file() and dataset_digest(path) == OFFICIAL_SHA256:
            return False
        staged.replace(path)
    return True
