"""Cliente MCP local com descoberta, limites e seleção JSON de ferramentas."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from time import perf_counter

from mcp import Client, StdioServerParameters

from .agent import object_schema, strict_json
from .mcp_server import ACTION_TOOL, MAX_RECORDS, READ_TOOLS, bounded, create_server

READ_PARAMS = {
    "consultar_janela": {"janela_id": {"type": "integer", "minimum": 1}},
    "consultar_historico": {"limite": {"type": "integer", "minimum": 1, "maximum": MAX_RECORDS}},
    "consultar_estado": {},
    "listar_acoes_permitidas": {},
    "encerrar": {},
}
READ_SCHEMA = {"oneOf": [
    object_schema({"ferramenta": {"const": name}, "parametros": object_schema(params)})
    for name, params in READ_PARAMS.items()
]}
READ_PROMPT = """Escolha uma consulta MCP e responda apenas com JSON contendo ferramenta e parametros.
Para investigar uma janela suspeita, consulte o histórico recente com limite 4 ou a janela atual
com seu ID real. Use somente as ferramentas de leitura listadas ou encerrar com parametros {}.
Se o resultado necessário já estiver disponível, escolha encerrar."""


async def discover(client):
    reply = await client.list_tools()
    tools = {tool.name: tool.description for tool in reply.tools}
    if set(tools) != {*READ_TOOLS, ACTION_TOOL} or reply.next_cursor is not None:
        raise ValueError("Catálogo MCP incompatível")
    return tools


async def call(client, name, params):
    result = await client.call_tool(name, params)
    if result.is_error:
        message = next((item.text for item in result.content if item.type == "text"), "erro MCP")
        raise ValueError(message[:500])
    if type(result.structured_content) is not dict:
        raise ValueError("Resposta MCP estruturada ausente")
    return bounded(result.structured_content)


def parse_read(raw):
    data = strict_json(raw)
    if not isinstance(data, dict) or set(data) != {"ferramenta", "parametros"}:
        raise ValueError("Seleção MCP incompatível")
    name, params = data["ferramenta"], data["parametros"]
    if not isinstance(name, str) or name not in READ_PARAMS or not isinstance(params, dict):
        raise ValueError("Ferramenta de leitura desconhecida")
    if set(params) != set(READ_PARAMS[name]) or any(type(v) is not int or v < 1 for v in params.values()):
        raise ValueError("Parâmetros MCP inválidos")
    if name == "consultar_historico" and params["limite"] > MAX_RECORDS:
        raise ValueError("Histórico MCP acima do limite")
    return name, params


class MCPWindow:
    def __init__(self, simulator, frame, detections, window_id, max_reads, timeout):
        self.simulator = simulator
        self.args = (simulator, frame, detections, window_id)
        self.server = create_server(*self.args, max_reads=max_reads, origin="ollama")
        self.timeout = timeout
        self.max_reads = max_reads
        self.audit = {"ferramentas": [], "catalogo": None, "prompt_selecao": READ_PROMPT, "schema_selecao": READ_SCHEMA}

    def _request(self, server, name=None, params=None):
        async def request():
            async with asyncio.timeout(self.timeout):
                async with Client(server, read_timeout_seconds=self.timeout) as client:
                    try:
                        return await (discover(client) if name is None else call(client, name, params))
                    except ValueError as error:
                        failure = str(error)
                raise ValueError(failure)

        start = perf_counter()
        record = {"nome": name, "parametros": params}
        self.audit["ferramentas"].append(record)
        try:
            result = asyncio.run(request())
            record["resultado"] = result
            return result
        except Exception as error:
            record["erro"] = str(error) or type(error).__name__
            raise ValueError(record["erro"]) from error
        finally:
            record["tempo_s"] = perf_counter() - start

    def consult(self, infer, context, remaining):
        catalog = self._request(self.server)
        self.audit["catalogo"] = catalog
        reads = []
        for _ in range(min(self.max_reads, remaining - 1)):
            query = {"janela": context["janela"], "situacao": context["detector"]["situacao"],
                     "ferramentas": READ_PARAMS, "catalogo": {name: catalog[name] for name in READ_TOOLS},
                     "consultas": list(reads)}
            name, params = parse_read(infer(READ_SCHEMA, READ_PROMPT, query))
            if name == "encerrar":
                break
            reads.append({"ferramenta": name, "resultado": self._request(self.server, name, params)})
            bounded(reads)
        return bounded({**context, "consultas_mcp": reads})

    def apply(self, proposal, origin):
        server = self.server if origin == "ollama" else create_server(*self.args, origin=origin)
        before = len(self.simulator.history())
        try:
            result = self._request(server, ACTION_TOOL, proposal)
            entries = self.simulator.history()[before:]
            if len(entries) == 1 and result == {key: entries[0][key] for key in result} and set(result) == {
                "id", "validacao", "execucao", "verificacao", "origem"
            }:
                return entries[0]
            raise ValueError("Resposta MCP divergente da auditoria local")
        except (ValueError, KeyError) as error:
            # Uma resposta perdida após o commit não deve disparar uma segunda ação.
            entries = self.simulator.history()[before:]
            self.audit["erro_acao"] = str(error)
            if len(entries) == 1:
                return entries[0]
            raise ValueError(str(error)) from error


async def demo():
    server = StdioServerParameters(command=sys.executable, args=["-m", "oran_lab.mcp_server"])
    async with asyncio.timeout(15):
        async with Client(server, read_timeout_seconds=5) as client:
            result = {"origem": "demonstracao_programada", "transporte": "stdio",
                      "ferramentas": await discover(client)}
            result["historico"] = await call(client, "consultar_historico", {"limite": 4})
            proposal = {"acao": "registrar_alerta", "parametros": {"evento_id": "alerta-5"},
                        "justificativa": "Episódio sintético da janela autorizada"}
            result["acao_valida"] = await call(client, ACTION_TOOL, proposal)
            result["acao_invalida"] = await call(client, ACTION_TOOL, proposal)
            result["estado"] = await call(client, "consultar_estado", {})
            return result


def main():
    parser = argparse.ArgumentParser(description="Demonstração MCP por stdio com dados sintéticos")
    parser.add_argument("--saida", type=Path, default=Path("results/etapa5/stdio.json"))
    args = parser.parse_args()
    result = asyncio.run(demo())
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.saida)


if __name__ == "__main__":
    main()
