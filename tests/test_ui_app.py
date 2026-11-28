"""Renderização e reruns com Streamlit AppTest."""

from pathlib import Path

import pytest

from oran_lab import ui_runs

pytest.importorskip("streamlit")
pytest.importorskip("plotly")
from streamlit.testing.v1 import AppTest
from oran_lab import ui_pages

APP = Path(ui_runs.__file__).with_name("ui_app.py")


def navigate(app, page):
    app.button(key=f"nav-{page}").click().run()
    selected = [button.label for button in app.sidebar.button if button.proto.type == "primary"]
    assert selected == [page]


def test_navigation_configure_and_monitor_with_reruns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ui_pages, "inventory", lambda: ("teste", []))
    ui_pages.local_inventory.clear()
    runs = []
    real_start = ui_runs.start_run

    def start(config, workspace, **kwargs):
        run_id = real_start(config, workspace, spawn=lambda *args: runs.append(args), **kwargs)
        ui_runs.run_worker(workspace, run_id, wait=lambda _: None)
        return run_id

    monkeypatch.setattr(ui_runs, "start_run", start)
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    assert not app.exception and app.title[0].value == "O-RAN Agentic Lab"
    navigate(app, "Configurar execução")
    assert not app.exception and app.title[0].value == "Configurar execução"
    next(b for b in app.button if b.label == "Iniciar execução").click().run()
    assert not app.exception and app.success
    app.run()
    assert len(runs) == 1
    navigate(app, "Monitoramento")
    assert not app.exception and len(app.get("plotly_chart")) == 2
    assert any(m.label == "Janela atual" and m.value == "8" for m in app.metric)
    navigate(app, "Inspeção do agente")
    assert not app.exception and any("Python" in c.value for c in app.caption)


def test_resource_pages_and_no_inference_preview(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def unavailable():
        raise ValueError("Ollama indisponível para o teste")

    monkeypatch.setattr(ui_pages, "inventory", unavailable)
    ui_pages.local_inventory.clear()
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    for page in ("Modelos de IA", "Datasets", "Base de conhecimento", "Cenários e presets", "Experimentos"):
        navigate(app, page)
        assert not app.exception and app.title[0].value == page
    next(button for button in app.button if button.label == "Gerar plano sem inferência").click().run()
    assert not app.exception and any(m.label == "Sessões" and m.value == "1" for m in app.metric)
    assert not list((tmp_path / "results/ui/experimentos").glob("*/manifesto.json"))


def test_navigation_keeps_drafts_and_selected_page(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ui_pages, "inventory", lambda: ("teste", []))
    ui_pages.local_inventory.clear()
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    assert len(app.sidebar.button) == 9 and not app.sidebar.expander
    navigate(app, "Configurar execução")
    size = "draft/run/demonstracao/A/0/size"
    app.number_input(key=size).set_value(4).run()
    navigate(app, "Experimentos")
    app.number_input(key="draft/exp/repetitions").set_value(2).run()
    navigate(app, "Configurar execução")
    assert app.number_input(key=size).value == 4
    navigate(app, "Experimentos")
    app.run()
    assert app.number_input(key="draft/exp/repetitions").value == 2
    assert app.button(key="nav-Experimentos").proto.type == "primary"
    assert not app.exception
