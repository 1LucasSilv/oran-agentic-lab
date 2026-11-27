"""Configura??o e cliente HTTP do Ollama em loopback."""

import json
import platform
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException
from math import isfinite
from urllib.parse import urlsplit

from .hardware import processor_name


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


class OllamaClient:
    def __init__(self, config):
        self.config = config

    def request(self, path, payload=None):
        url = urlsplit(self.config.url)
        conn = HTTPConnection(url.hostname, url.port or 80, timeout=self.config.timeout)
        try:
            body = json.dumps(payload, allow_nan=False).encode("utf-8") if payload is not None else None
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

    def local_model(self):
        tag = self.config.model
        if ":" not in tag.split("/")[-1]:
            tag += ":latest"
        model = next((m for m in self.info("/api/tags").get("models", []) if m.get("name") == tag), {})
        if model.get("remote_model") or model.get("remote_host"):
            raise ValueError("Modelo remoto incompatível com a execução local")
        return model

    def metadata(self):
        version = self.info("/api/version").get("version")
        model = self.local_model()
        return {"ollama": version, "digest": model.get("digest"),
                "quantizacao": model.get("details", {}).get("quantization_level"),
                "arquitetura_host": platform.machine(), "processador_host": processor_name()}

    def residency(self):
        names = {self.config.model, self.config.model + ":latest"}
        model = next((m for m in self.info("/api/ps").get("models", []) if m.get("name") in names), {})
        return {k: model.get(k) for k in ("size", "size_vram", "context_length")}
