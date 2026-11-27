"""Cliente Ollama local, contrato das propostas e auditoria das decisões."""

import json
from dataclasses import asdict
from hashlib import sha256
from http.client import HTTPException
from time import perf_counter

from .detector import SUSPECT
from .ollama import AgentConfig, OllamaClient, strict_json
from .simulator import ACTION_PARAMETERS, NO_ACTION, PRIORITIES, REGISTER_ALERT

PROMPT_VERSION = "kpm-v2"
SYSTEM_PROMPT = """Você analisa janelas históricas de KPMs. Use somente os dados fornecidos.
Proponha uma única ação do simulador. Responda exclusivamente com um objeto JSON com
acao, parametros e justificativa objetiva em português. Use os nomes e tipos indicados.
Escolha acao na lista acoes_com_alvo_disponivel. Um alerta_id do detector só vira evento
após registrar_alerta. Para registrar um novo episódio suspeito use alerta_id como evento_id.
Se a única opção disponível for nenhuma_acao, retorne essa ação com parametros {}.
Para um evento existente, considere uma investigação limitada quando houver evidência.
Use nenhuma_acao com parametros {} quando não houver indicação, inclusive evidência insuficiente.
Nunca invente medições, identificadores ou efeitos. Register indica ordem. Latency tem semântica
temporal incerta. PRB está em escala bruta. Uma queda relativa é evidência heurística, não
comprova falha ou congestionamento. Intensificar inspeção configura apenas uma passagem futura.
As ações alteram somente o simulador. Nunca proponha comandos ou acesso externo."""

PARAM_TYPES = {
    "evento_id": {"type": "string", "minLength": 1},
    "prioridade": {"type": "string", "enum": list(PRIORITIES)},
    "tamanho_registros": {"type": "integer", "minimum": 1},
    "avanco_registros": {"type": "integer", "minimum": 1},
}


def object_schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


SCHEMA = {"oneOf": [
    object_schema({"acao": {"const": action},
                   "parametros": object_schema({k: PARAM_TYPES[k] for k in sorted(keys)}),
                   "justificativa": {"type": "string", "minLength": 1}})
    for action, keys in ACTION_PARAMETERS.items()
]}


def parse_proposal(raw):
    obj = strict_json(raw)
    if type(obj) is not dict or set(obj) != {"acao", "parametros", "justificativa"}:
        raise ValueError("Campos inválidos na proposta")
    action, params = obj["acao"], obj["parametros"]
    if type(action) is not str or action not in ACTION_PARAMETERS:
        raise ValueError("Ação desconhecida")
    if type(params) is not dict or set(params) != ACTION_PARAMETERS[action]:
        raise ValueError("Parâmetros incompatíveis com a ação")
    if not isinstance(obj["justificativa"], str) or not obj["justificativa"].strip():
        raise ValueError("Justificativa textual obrigatória")
    for key, value in params.items():
        spec = PARAM_TYPES[key]
        if spec["type"] == "integer":
            if type(value) is not int or value < 1:
                raise ValueError(f"{key} deve ser inteiro positivo")
        elif type(value) is not str or not value.strip() or ("enum" in spec and value not in spec["enum"]):
            raise ValueError(f"Valor inválido para {key}")
    return obj


def build_context(detection, state, limits):
    window = detection["janela"]
    identity = {"id": window["id"], "segmento": window["segmento"], "completa": window["completa"],
                "primeiro_register": window["registros"][0], "ultimo_register": window["registros"][-1]}
    evidence = {key: detection[key] for key in (
        "situacao", "regra", "metricas", "parametros", "referencia", "variacao_relativa_referencia",
        "variacao_relativa_anterior", "persistencia_janelas", "alerta_id", "novo_alerta")}
    # O episódio corrente é o contexto pertinente. Outros episódios não são enviados em massa.
    event_id = detection["alerta_id"]
    event = state["eventos"].get(event_id)
    event_context = None
    if event:
        event_context = {"evento_id": event_id, "prioridade": event["prioridade"],
                         "tamanho_registros": event["analise"]["tamanho_registros"]}
    available = [NO_ACTION]
    if event:
        available.extend(action for action in ACTION_PARAMETERS if action not in (NO_ACTION, REGISTER_ALERT))
    elif detection["novo_alerta"]:
        available.append(REGISTER_ALERT)
    return {"janela": identity, "detector": evidence, "evento_atual": event_context,
            "acoes_com_alvo_disponivel": available,
            "inspecao": state["inspecao"], "analise": state["analise"], "limites": asdict(limits),
            "acoes": {name: {k: PARAM_TYPES[k] for k in sorted(keys)} for name, keys in ACTION_PARAMETERS.items()}}


class AgentSession:
    """Uma sessão por execução. A política hospedeira fornece o fallback."""

    def __init__(self, config, client=None):
        self.config = config
        self.client = client or OllamaClient(config)
        self.calls = self.failures = self.consecutive = 0
        self.decisions = []
        self.metadata = self.client.metadata()

    def _skip(self, detection):
        if self.config.selection == "suspeitas" and detection["situacao"] != SUSPECT:
            return "fora_da_selecao"
        if self.consecutive >= self.config.max_failures:
            return "circuito_aberto"
        if self.calls >= self.config.max_calls:
            return "orcamento_esgotado"
        return None

    def _infer(self, schema, system, context, audit):
        config = self.config
        options = {k: getattr(config, k) for k in ("temperature", "num_ctx", "num_predict")}
        if config.seed is not None:
            options["seed"] = config.seed
        payload = {"model": config.model, "stream": False, "format": schema, "options": options,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": json.dumps(context, ensure_ascii=False)}]}
        self.calls += 1
        call_start = perf_counter()
        try:
            status, raw = self.client.request("/api/chat", payload)
        finally:
            audit["tempo_chamada_s"] = perf_counter() - call_start
        audit.update(status_http=status, resposta_http=raw)
        if status != 200:
            raise ValueError(f"Ollama HTTP {status}")
        response = strict_json(raw)
        if not isinstance(response, dict):
            raise ValueError("Envelope Ollama inválido")
        audit["metricas_ollama"] = {k: response.get(k) for k in (
            "model", "eval_count", "prompt_eval_count", "prompt_eval_cached_count", "eval_duration", "prompt_eval_duration",
            "total_duration", "load_duration", "done_reason")}
        message = response.get("message")
        if (response.get("done") is not True or response.get("done_reason") not in (None, "stop")
                or not isinstance(message, dict) or message.get("role") != "assistant"
                or message.get("tool_calls") or type(message.get("content")) is not str):
            raise ValueError("Resposta incompleta ou incompatível com /api/chat")
        return message["content"]

    def _consult_model(self, schema, prompt, context, audit):
        record = {"contexto": context, "resposta_http": None}
        audit.setdefault("inferencias_consulta", []).append(record)
        return self._infer(schema, prompt, context, record)

    def decide(self, detection, simulator, baseline, mcp=None):
        start = perf_counter()
        config = self.config
        window_id = detection["janela"]["id"]
        skip = self._skip(detection)
        audit = {"janela_id": window_id, "dispensa": skip, "contexto": None, "resposta_http": None,
                 "proposta_modelo": None, "historico_modelo": None, "erro": None, "fallback": None,
                 "tempo_chamada_s": None, "metricas_ollama": None}
        if mcp:
            audit["mcp"] = mcp.audit
        origin = "politica_deterministica"
        entry = None
        if not skip:
            context = build_context(detection, simulator.state(), simulator.limits)
            audit["contexto"] = context
            try:
                if mcp:
                    audit["contexto_final"] = mcp.consult(
                        lambda schema, prompt, query: self._consult_model(schema, prompt, query, audit),
                        context, config.max_calls - self.calls,
                    )
                proposal = parse_proposal(self._infer(SCHEMA, SYSTEM_PROMPT, audit.get("contexto_final", context), audit))
                audit["proposta_modelo"] = proposal
            except (OSError, HTTPException, ValueError, RecursionError) as error:
                audit["erro"] = f"{type(error).__name__}: {error}"
            else:
                try:
                    entry = (mcp.apply(proposal, "ollama") if mcp
                             else simulator.apply(proposal, origin="ollama", window_id=window_id))
                except ValueError as error:
                    audit["erro"] = str(error)
                if entry is not None:
                    audit["historico_modelo"] = entry["id"]
                    if entry["validacao"]["estado"] == "recusada" or entry["execucao"]["estado"] == "falha":
                        audit["erro"] = entry["execucao"]["justificativa"]
                        entry = None
            if audit["erro"]:
                self.consecutive += 1
                self.failures += 1
            else:
                self.consecutive = 0
        if entry is None:
            proposal = baseline(detection)
            if audit["erro"] or skip == "circuito_aberto":
                origin = "fallback_python"
                audit["fallback"] = proposal
            try:
                entry = (mcp.apply(proposal, origin) if mcp
                         else simulator.apply(proposal, origin=origin, window_id=window_id))
            except ValueError as error:
                audit["erro"] = audit["erro"] or str(error)
                proposal = {"acao": NO_ACTION, "parametros": {}, "justificativa": "Canal de ação MCP indisponível"}
                audit["fallback"] = proposal
                entry = simulator.apply(proposal, origin="fallback_python", window_id=window_id)
        audit.update(historico_final=entry["id"], origem_decisao_final=entry["origem"],
                     origem_execucao=entry["origem"] if entry["execucao"]["estado"] == "executada" else None,
                     tempo_decisao_s=perf_counter() - start)
        self.decisions.append(audit)

    def report(self):
        calls = [call for decision in self.decisions
                 for call in [*decision.get("inferencias_consulta", []), decision]]
        totals = {}
        for key in ("eval_count", "prompt_eval_count", "eval_duration", "prompt_eval_duration"):
            values = [(d["metricas_ollama"] or {}).get(key) for d in calls]
            observed = [value for value in values if type(value) is int and value >= 0]
            totals[key] = sum(observed) if observed else None
        return {"config": asdict(self.config), "metadados": self.metadata, "residencia_final": self.client.residency(),
                "prompt_versao": PROMPT_VERSION, "prompt_sha256": sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
                "prompt": SYSTEM_PROMPT, "schema": SCHEMA, "chamadas": self.calls, "falhas": self.failures,
                "fallbacks": sum(d["fallback"] is not None for d in self.decisions),
                "propostas_modelo_aceitas_verificadas": sum(d["origem_decisao_final"] == "ollama" for d in self.decisions),
                "acoes_executadas_modelo": sum(d["origem_execucao"] == "ollama" for d in self.decisions),
                "totais_ollama_informados": totals,
                "tempo_chamadas_s": sum(d["tempo_chamada_s"] or 0 for d in calls),
                "tempo_decisoes_s": sum(d["tempo_decisao_s"] for d in self.decisions), "decisoes": self.decisions}
