"""Diagnostica o ambiente local sem instalar dependências ou baixar recursos."""

import argparse
import os
import platform
import shutil
import sys
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if sys.version_info < (3, 11):
    raise SystemExit(f"Python {platform.python_version()} encontrado. Use Python 3.11 ou superior.")

import tomllib

sys.path.insert(0, str(ROOT / "src"))

from oran_lab.dataset import OFFICIAL_PATH, OFFICIAL_SHA256, dataset_digest
from oran_lab.hardware import physical_memory, processor_name
from oran_lab.ollama import AgentConfig, OllamaClient


def check_dependencies(requirements, group) -> bool:
    ready = True
    for requirement in requirements:
        name, _, expected = requirement.partition("==")
        module_name = "oran_lab" if name == "oran-agentic-lab" else name.replace("-", "_")
        try:
            installed = version(name)
            module = import_module(module_name)
            if name == "mcp":
                for symbol in ("Client", "StdioServerParameters"):
                    getattr(module, symbol)
                getattr(import_module("mcp.server.mcpserver"), "MCPServer")
        except PackageNotFoundError:
            detail, ok = "ausente", False
        except (ImportError, AttributeError, OSError) as error:
            detail, ok = f"importação falhou ({error})", False
        else:
            ok = not expected or expected == installed
            detail = installed if ok else f"{installed} (fixado {expected})"
        print(f"[{group}] {name} — {detail}")
        ready &= ok
    return ready


def check_dataset(path: Path) -> None:
    try:
        digest = dataset_digest(path)
    except FileNotFoundError:
        status = "ausente"
    except OSError as error:
        status = f"erro de leitura ({error})"
    else:
        status = "SHA-256 válido" if digest == OFFICIAL_SHA256 else f"SHA-256 divergente ({digest})"
    print(f"[dados oficiais] {status} — {path}")


def find_ollama() -> str | None:
    command = shutil.which("ollama")
    if not command and platform.system() == "Windows" and os.getenv("LOCALAPPDATA"):
        path = Path(os.environ["LOCALAPPDATA"], "Programs", "Ollama", "ollama.exe")
        if path.is_file():
            return str(path)
    return command


def check_ollama(config: AgentConfig) -> None:
    print(f"[opcional] CLI Ollama — {find_ollama() or 'não localizada'}")
    client = OllamaClient(config)
    runtime = client.info("/api/version").get("version")
    print(f"[opcional] Serviço {config.url} — {runtime or 'indisponível'}")
    if not runtime:
        detail = "indeterminado sem serviço"
    else:
        try:
            model = client.local_model()
        except ValueError as error:
            detail = str(error)
        else:
            detail = f"disponível (digest {model.get('digest', 'desconhecido')})" if model else "não localizado"
    print(f"[opcional] Modelo {config.model} — {detail}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / OFFICIAL_PATH)
    parser.add_argument("--modelo", default=AgentConfig.model)
    parser.add_argument("--api", default=AgentConfig.url)
    args = parser.parse_args(argv)
    try:
        config = AgentConfig(model=args.modelo, url=args.api, timeout=2)
    except ValueError as error:
        parser.error(str(error))

    print(f"Sistema — {platform.platform()} ({platform.machine()})")
    print(f"Processador — {processor_name() or 'desconhecido'}, {os.cpu_count() or '?'} CPUs lógicas")
    memory = physical_memory()
    print(f"RAM física — {f'{memory / 2**30:.1f} GiB' if memory else 'desconhecida'}")
    print(f"Disco livre no projeto — {shutil.disk_usage(ROOT).free / 2**30:.1f} GiB")
    print(f"[obrigatório] Python — {platform.python_version()} ({sys.executable})")
    print(f"Ambiente virtual ativo — {'sim' if sys.prefix != sys.base_prefix else 'não'}")
    with (ROOT / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]
    core_ready = check_dependencies([project["name"], *project["dependencies"]], "obrigatório")
    check_dependencies(project["optional-dependencies"]["test"], "opcional para testes")
    check_dependencies(project["optional-dependencies"]["mcp"], "opcional para MCP")
    check_dependencies(project["optional-dependencies"]["rag"], "opcional para RAG")
    check_dataset(args.dataset)
    check_ollama(config)
    return 0 if core_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
