"""Cliente Ollama local, contrato das propostas e auditoria das decisões."""

import json
import platform
from dataclasses import asdict, dataclass
from hashlib import sha256
from http.client import HTTPConnection, HTTPException
from math import isfinite
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

from .detector import SUSPECT
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


@dataclass(frozen=True)
class AgentConfig:
    model: str = "qwen2.5:1.5b"
    url: str = "http://127.0.0.1:11434"
    timeout: float = 90
    temperature: float = 0
    seed: int | None = 42
    num_ctx: int = 4096
    num_predict: int = 256
    max_calls: int = 4
    max_failures: int = 2
    selection: str = "suspeitas"

    def __post_init__(self):
        url = urlsplit(self.url)
        if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost", "::1")
                or url.username is not None or url.password is not None or url.query or url.fragment
                or url.path not in ("", "/") or url.port == 0):
            raise ValueError("Use uma URL HTTP de loopback sem credenciais, caminho ou consulta")
        if not self.model.strip() or self.model.endswith((":cloud", "-cloud")):
            raise ValueError("Informe uma tag de modelo local")
        if self.seed is not None and type(self.seed) is not int:
            raise ValueError("Seed deve ser inteira ou ausente")
        if self.selection not in ("suspeitas", "todas"):
            raise ValueError("Seleção deve ser suspeitas ou todas")
        if not isfinite(self.timeout) or self.timeout <= 0 or not 0 <= self.temperature <= 2:
            raise ValueError("Timeout ou temperatura inválidos")
        for value, minimum in ((self.num_ctx, 1), (self.num_predict, 1), (self.max_calls, 0),
                               (self.max_failures, 1)):
            if type(value) is not int or value < minimum:
                raise ValueError("Limites de contexto, geração, chamadas ou falhas inválidos")


def strict_json(raw):
    def reject_duplicates(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f"Campo duplicado: {key}")
            obj[key] = value
        return obj

    obj = json.loads(raw, object_pairs_hook=reject_duplicates)
    json.dumps(obj, allow_nan=False, ensure_ascii=False).encode("utf-8")
    return obj


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


class OllamaClient:
    def __init__(self, config):
        self.config = config

    def request(self, path, payload=None):
        url = urlsplit(self.config.url)
        conn = HTTPConnection(url.hostname, url.port or 80, timeout=self.config.timeout)
        try:
            body = json.dumps(payload, allow_nan=False).encode() if payload is not None else None
            conn.request("POST" if body else "GET", path, body, {"Content-Type": "application/json"})
            response = conn.getresponse()
            raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError("Resposta excede 1 MiB")
            return response.status, raw.decode("utf-8")
        finally:
            conn.close()

    def info(self, path):
        try:
            status, raw = self.request(path)
            obj = strict_json(raw)
            return obj if status == 200 and isinstance(obj, dict) else {}
        except (ValueError, OSError, HTTPException, RecursionError):
            return {}

    def metadata(self):
        version = self.info("/api/version").get("version")
        tag = self.config.model
        if ":" not in tag.split("/")[-1]:
            tag += ":latest"
        model = next((m for m in self.info("/api/tags").get("models", []) if m.get("name") == tag), {})
        if model.get("remote_model") or model.get("remote_host"):
            raise ValueError("Modelo remoto incompatível com a execução local")
        cpu = platform.processor() or None
        try:
            info = Path("/proc/cpuinfo").read_text()
            cpu = next((line.partition(":")[2].strip() for line in info.splitlines()
                        if line.startswith("model name")), cpu)
        except OSError:
            pass
        return {"ollama": version, "digest": model.get("digest"),
                "quantizacao": model.get("details", {}).get("quantization_level"),
                "arquitetura_host": platform.machine(), "processador_host": cpu}

    def residency(self):
        names = {self.config.model, self.config.model + ":latest"}
        model = next((m for m in self.info("/api/ps").get("models", []) if m.get("name") in names), {})
        return {k: model.get(k) for k in ("size", "size_vram", "context_length")}


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

    def decide(self, detection, simulator, baseline):
        start = perf_counter()
        config = self.config
        window_id = detection["janela"]["id"]
        skip = self._skip(detection)
        audit = {"janela_id": window_id, "dispensa": skip, "contexto": None, "resposta_http": None,
                 "proposta_modelo": None, "historico_modelo": None, "erro": None, "fallback": None,
                 "tempo_chamada_s": None, "metricas_ollama": None}
        origin = "politica_deterministica"
        entry = None
        if not skip:
            context = build_context(detection, simulator.state(), simulator.limits)
            audit["contexto"] = context
            options = {k: getattr(config, k) for k in ("temperature", "num_ctx", "num_predict")}
            if config.seed is not None:
                options["seed"] = config.seed
            payload = {"model": config.model, "stream": False, "format": SCHEMA, "options": options,
                       "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                    {"role": "user", "content": json.dumps(context, ensure_ascii=False)}]}
            self.calls += 1
            call_start = perf_counter()
            try:
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
                proposal = parse_proposal(message["content"])
                audit["proposta_modelo"] = proposal
            except (OSError, HTTPException, ValueError, RecursionError) as error:
                audit["erro"] = f"{type(error).__name__}: {error}"
            else:
                entry = simulator.apply(proposal, origin="ollama", window_id=window_id)
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
            entry = simulator.apply(proposal, origin=origin, window_id=window_id)
        audit.update(historico_final=entry["id"], origem_decisao_final=entry["origem"],
                     origem_execucao=entry["origem"] if entry["execucao"]["estado"] == "executada" else None,
                     tempo_decisao_s=perf_counter() - start)
        self.decisions.append(audit)

    def report(self):
        totals = {}
        for key in ("eval_count", "prompt_eval_count", "eval_duration", "prompt_eval_duration"):
            values = [(d["metricas_ollama"] or {}).get(key) for d in self.decisions]
            observed = [value for value in values if type(value) is int and value >= 0]
            totals[key] = sum(observed) if observed else None
        return {"config": asdict(self.config), "metadados": self.metadata, "residencia_final": self.client.residency(),
                "prompt_versao": PROMPT_VERSION, "prompt_sha256": sha256(SYSTEM_PROMPT.encode()).hexdigest(),
                "prompt": SYSTEM_PROMPT, "schema": SCHEMA, "chamadas": self.calls, "falhas": self.failures,
                "fallbacks": sum(d["fallback"] is not None for d in self.decisions),
                "propostas_modelo_aceitas_verificadas": sum(d["origem_decisao_final"] == "ollama" for d in self.decisions),
                "acoes_executadas_modelo": sum(d["origem_execucao"] == "ollama" for d in self.decisions),
                "totais_ollama_informados": totals,
                "tempo_chamadas_s": sum(d["tempo_chamada_s"] or 0 for d in self.decisions),
                "tempo_decisoes_s": sum(d["tempo_decisao_s"] for d in self.decisions), "decisoes": self.decisions}
