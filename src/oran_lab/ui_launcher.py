"""Lançador da interface local sem dependência Streamlit para os demais comandos."""

import argparse
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description="O-RAN Agentic Lab · interface local")
    parser.add_argument("--porta", type=int, default=8501)
    args = parser.parse_args(argv)
    if not 1 <= args.porta <= 65535:
        parser.error("A porta deve estar entre 1 e 65535.")
    if find_spec("streamlit") is None or find_spec("plotly") is None:
        parser.error('Instale o extra com python -m pip install -e ".[ui]".')
    app = Path(__file__).with_name("ui_app.py")
    command = [sys.executable, "-m", "streamlit", "run", str(app),
               "--server.address=127.0.0.1", f"--server.port={args.porta}",
               "--server.headless=true", "--server.fileWatcherType=none",
               "--server.enableXsrfProtection=true", "--server.enableCORS=true",
               "--browser.gatherUsageStats=false", "--theme.base=dark",
               "--theme.primaryColor=#4CE4CF", "--theme.backgroundColor=#09131E",
               "--theme.secondaryBackgroundColor=#132333", "--theme.textColor=#E5EDF4"]
    print(f"O-RAN Agentic Lab · http://127.0.0.1:{args.porta}", flush=True)
    try:
        return subprocess.run(command, check=False).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
