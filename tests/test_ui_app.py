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
    app.text_input(key="draft/run-name").set_value("Demonstração nomeada").run()
    next(b for b in app.button if b.label == "Iniciar execução").click().run()
    assert not app.exception and "Demonstração nomeada" in app.success[0].value
    assert "Demonstração nomeada" not in next(tmp_path.glob("results/ui/*/manifesto.json")).read_text(encoding="utf-8")
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
    assert len(app.sidebar.button) == 13 and not app.sidebar.expander
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


def test_new_research_pages_use_only_stored_evidence(tmp_path, monkeypatch):
    from oran_lab.ui_experiments import Comparison, plan_comparison, run_worker, start_comparison

    monkeypatch.chdir(tmp_path)
    plan = plan_comparison(Comparison(ui_runs.RunConfig(), ("demonstracao",), ("A",), (42,), target=5), tmp_path)
    identifier = start_comparison(plan, tmp_path, confirmed=True, spawn=lambda *_: None)
    run_worker(tmp_path, identifier)
    calls = []
    monkeypatch.setattr(ui_pages, "inventory", lambda: (calls.append("inventory") or ("teste", [])))
    ui_pages.local_inventory.clear()
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    calls.clear()
    for page in ("Central de execução", "Resultados", "Avaliação científica", "Modo apresentação"):
        navigate(app, page)
        assert not app.exception and app.title[0].value == page
    assert not any("Decisão da janela" in heading.value for heading in app.subheader)
    next(button for button in app.button if button.label == "Avançar janela").click().run()
    assert not app.exception and any(heading.value == "Decisão da janela 5" for heading in app.subheader)
    next(button for button in app.button if button.label == "Retroceder evento").click().run()
    assert not any("Decisão da janela" in heading.value for heading in app.subheader)
    assert not calls


def test_history_routes_to_pinned_record_and_keeps_it_on_rerun(tmp_path, monkeypatch):
    from test_ui_history import operational_record

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ui_pages, "inventory", lambda: ("teste", []))
    ui_pages.local_inventory.clear()
    first = "a" * 32
    old = "b" * 32
    operational_record(tmp_path, first, "2026-11-28T04:00:00+00:00")
    operational_record(tmp_path, old, "2026-11-28T03:00:00+00:00")
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    navigate(app, "Monitoramento")
    selected = "pick/monitor_run"
    assert app.selectbox(key=selected).value == f"Operacional/{first}"
    app.selectbox(key=selected).set_value(f"Operacional/{old}").run()
    navigate(app, "Visão geral")
    operational_record(tmp_path, "c" * 32, "2026-11-28T05:00:00+00:00")
    navigate(app, "Monitoramento")
    assert not app.exception and app.selectbox(key=selected).value == f"Operacional/{old}"
    navigate(app, "Visão geral")
    app.button(key=f"history-Operacional/{first}-Monitoramento").click().run()
    assert app.selectbox(key=selected).value == f"Operacional/{first}"


def test_experiment_launch_keeps_visual_name_outside_manifest(tmp_path, monkeypatch):
    from oran_lab.ui_experiments import start_comparison

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ui_pages, "inventory", lambda: ("teste", []))
    monkeypatch.setattr(ui_pages, "start_comparison", lambda *args, **kw: start_comparison(*args, **kw, spawn=lambda *_: None))
    ui_pages.local_inventory.clear()
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    navigate(app, "Experimentos")
    app.text_input(key="draft/experiment-name").set_value("Comparação demonstrativa").run()
    next(button for button in app.button if button.label == "Gerar plano sem inferência").click().run()
    next(widget for widget in app.checkbox if widget.label.startswith("Autorizo iniciar")).check()
    next(button for button in app.button if button.label == "Executar plano").click().run()
    assert not app.exception and app.title[0].value == "Central de execução"
    assert any("Comparação demonstrativa" in option for option in app.selectbox(key="pick/central").options)
    [manifest] = tmp_path.glob("results/ui/experimentos/*/manifesto.json")
    assert "Comparação demonstrativa" not in manifest.read_text(encoding="utf-8")
