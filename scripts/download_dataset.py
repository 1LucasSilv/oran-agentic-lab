"""Baixa ou verifica a revisão auditada da planilha oficial."""

import argparse
import sys
from http.client import HTTPException
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oran_lab.dataset import OFFICIAL_PATH, OFFICIAL_SHA256, prepare_dataset


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destino", type=Path, default=ROOT / OFFICIAL_PATH, help="Caminho do arquivo .xlsx")
    parser.add_argument("--verificar", action="store_true", help="Confere o SHA-256 sem usar a rede")
    args = parser.parse_args(argv)
    try:
        downloaded = prepare_dataset(args.destino, check_only=args.verificar)
    except (OSError, ValueError, HTTPException) as error:
        print(f"{args.destino} — {error}", file=sys.stderr)
        return 1
    print(f"{'Download verificado' if downloaded else 'Arquivo válido preservado'} — {args.destino}")
    print(f"SHA-256 {OFFICIAL_SHA256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
