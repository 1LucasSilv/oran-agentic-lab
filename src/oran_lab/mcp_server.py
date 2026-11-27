"""Ferramentas locais vinculadas à janela autorizada pelo hospedeiro."""

import json
from typing import Annotated, Any

import pandas as pd
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from .agent import build_context, strict_json
from .detector import METRICS

MAX_RECORDS = 32
MAX_RESULT_BYTES = 8192
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
READ_TOOLS = ("consultar_janela", "consultar_historico", "consultar_estado", "listar_acoes_permitidas")
ACTION_TOOL = "solicitar_acao"
TOOL_PARAMS = {
    "consultar_janela": {"janela_id"},
    "consultar_historico": {"limite"},
    "consultar_estado": set(),
    "listar_acoes_permitidas": set(),
    ACTION_TOOL: {"acao", "parametros", "justificativa"},
}


class LocalServer(MCPServer):
    async def call_tool(self, name, arguments, context=None):
        if name in TOOL_PARAMS and set(arguments) != TOOL_PARAMS[name]:
            return CallToolResult(is_error=True, content=[TextContent(type="text", text="Parâmetros MCP inválidos")])
        return await super().call_tool(name, arguments, context)


def bounded(result):
    if len(json.dumps(result, allow_nan=False, ensure_ascii=False).encode("utf-8")) > MAX_RESULT_BYTES:
        raise ValueError("Resultado MCP excede o limite de bytes")
    return result


def create_server(simulator, frame, detections, window_id, *, max_reads=2, origin="cliente_mcp"):
    """Cria uma superfície MCP com escopo fixo e o simulador da execução."""
    window = detections[window_id]
    last_register = window["janela"]["registros"][-1]
    end = window["janela"]["ultima_linha_excel"] - 1
    server = LocalServer("oran-agentic-lab")
    reads = 0

    def charge():
        nonlocal reads
        if reads >= max_reads:
            raise ToolError("Orçamento de consultas MCP esgotado")
        reads += 1

    def context(item=window):
        return build_context(item, simulator.state(), simulator.limits)

    @server.tool(structured_output=True)
    async def consultar_janela(janela_id: PositiveInt) -> dict[str, Any]:
        """Consulta evidências agregadas da janela atual ou de uma janela anterior."""
        charge()
        item = detections.get(janela_id)
        if janela_id > window_id or item is None or item["janela"]["registros"][-1] > last_register:
            raise ToolError("Janela fora do contexto autorizado")
        data = context(item)
        return bounded({"janela": data["janela"], "detector": data["detector"]})

    @server.tool(structured_output=True)
    async def consultar_historico(limite: PositiveInt) -> dict[str, Any]:
        """Retorna até 32 registros terminando na janela atual, em ordem de Register."""
        charge()
        if limite > MAX_RECORDS:
            raise ToolError(f"Limite máximo de {MAX_RECORDS} registros")
        rows = frame.iloc[max(0, end - limite):end].reindex(columns=["Register", *METRICS])
        return bounded({"registros": strict_json(rows.apply(pd.to_numeric, errors="coerce").to_json(orient="records"))})

    @server.tool(structured_output=True)
    async def consultar_estado() -> dict[str, Any]:
        """Consulta o evento do episódio atual, o orçamento e a configuração de inspeção."""
        charge()
        data = context()
        return bounded({key: data[key] for key in ("evento_atual", "analise", "inspecao", "limites")})

    @server.tool(structured_output=True)
    async def listar_acoes_permitidas() -> dict[str, Any]:
        """Lista ações com alvo disponível neste contexto e seus parâmetros."""
        charge()
        data = context()
        return bounded({"acoes": {name: data["acoes"][name] for name in data["acoes_com_alvo_disponivel"]}})

    @server.tool(structured_output=True)
    async def solicitar_acao(acao: str, parametros: dict, justificativa: str) -> dict[str, Any]:
        """Submete uma ação do simulador ao validador e retorna o resultado auditado."""
        proposal = {"acao": acao, "parametros": parametros, "justificativa": justificativa}
        bounded(proposal)
        entry = simulator.apply(proposal, origin=origin, window_id=window_id)
        return {key: entry[key] for key in ("id", "validacao", "execucao", "verificacao", "origem")}

    return server


def main():
    from .detector import DetectorConfig, detect
    from .loop import _synthetic_frame
    from .replay import ReplayConfig
    from .simulator import Simulator

    frame, _ = _synthetic_frame()
    replay = ReplayConfig(size=2)
    items = list(detect(frame, replay, DetectorConfig()))
    simulator = Simulator(frame, items, replay.advance)
    create_server(simulator, frame, {d["janela"]["id"]: d for d in items}, 5).run()


if __name__ == "__main__":
    main()
