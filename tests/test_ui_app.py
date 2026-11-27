"""Renderização e reruns com Streamlit AppTest."""

from pathlib import Path

import pytest

from oran_lab import ui_runs

pytest.importorskip("streamlit")
pytest.importorskip("plotly")
from streamlit.testing.v1 import AppTest

APP = Path(ui_runs.__file__).with_name("ui_app.py")


def test_navigation_configure_and_monitor_with_reruns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runs = []
    real_start = ui_runs.start_run

    def start(config, workspace, **kwargs):
        run_id = real_start(config, workspace, spawn=lambda *args: runs.append(args), **kwargs)
        ui_runs.run_worker(workspace, run_id, wait=lambda _: None)
        return run_id

    monkeypatch.setattr(ui_runs, "start_run", start)
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    assert not app.exception and app.title[0].value == "O-RAN Agentic Lab"
    app.radio[0].set_value("Configurar execução").run()
    assert not app.exception and app.title[0].value == "Configurar execução"
    next(b for b in app.button if b.label == "Iniciar execução").click().run()
    assert not app.exception and app.success
    app.run()
    assert len(runs) == 1
    app.radio[0].set_value("Monitoramento").run()
    assert not app.exception and len(app.get("plotly_chart")) == 2
    assert any(m.label == "Janela atual" and m.value == "8" for m in app.metric)
    app.radio[0].set_value("Inspeção do agente").run()
    assert not app.exception and any("Python" in c.value for c in app.caption)
