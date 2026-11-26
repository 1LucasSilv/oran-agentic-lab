"""Validação, execução e auditoria de transições locais do simulador."""

import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from math import isfinite
from threading import Lock

import pandas as pd

from .detector import METRICS, SUSPECT, THROUGHPUT, summarize_metric
from .replay import validated_registers

REGISTER_ALERT = "registrar_alerta"
PRIORITIZE = "priorizar_evento"
EXPAND = "ampliar_janela_analise"
INTENSIFY = "ativar_monitoramento_intensificado"
NO_ACTION = "nenhuma_acao"

PRIORITIES = ("baixa", "normal", "alta")
ACTION_PARAMETERS = {
    REGISTER_ALERT: {"evento_id"},
    PRIORITIZE: {"evento_id", "prioridade"},
    EXPAND: {"evento_id", "tamanho_registros"},
    INTENSIFY: {"evento_id", "avanco_registros"},
    NO_ACTION: set(),
}


@dataclass(frozen=True)
class Limits:
    max_history_size: int = 120
    history_budget: int = 240
    min_inspection_stride: int = 1

    def __post_init__(self):
        if (type(self.max_history_size) is not int or self.max_history_size < 1
                or type(self.history_budget) is not int or self.history_budget < 0
                or type(self.min_inspection_stride) is not int or self.min_inspection_stride < 1):
            raise ValueError("Limites inválidos para tamanho, orçamento ou avanço de inspeção")


@dataclass(frozen=True)
class Validation:
    reason: str
    accepted: bool = False
    changes_state: bool = False


class Simulator:
    """Uma sessão local vinculada ao histórico e às detecções de uma única execução."""

    def __init__(self, frame: pd.DataFrame, detections, base_stride: int, limits: Limits = Limits()):
        if type(base_stride) is not int or base_stride < limits.min_inspection_stride:
            raise ValueError("O avanço inicial deve respeitar o mínimo de inspeção")
        self.limits = limits
        self._registers = validated_registers(frame)
        self._positions = {register: i for i, register in enumerate(self._registers)}
        self._metrics = frame.reindex(columns=METRICS).copy()
        self._detections = {}
        for detection in detections:
            window = detection["janela"]
            window_id = window["id"]
            if type(window_id) is not int or window_id < 1 or window_id in self._detections:
                raise ValueError("O catálogo de detecções deve ter identificadores de janela únicos e positivos")
            self._detections[window_id] = deepcopy(detection)
        self._state = {
            "alertas": {},
            "eventos": {},
            "analise": {"registros_adicionais_consultados": 0},
            "inspecao": {"avanco_registros": base_stride},
        }
        self._history = []
        self._lock = Lock()

    def state(self) -> dict:
        return deepcopy(self._state)

    def history(self) -> list[dict]:
        with self._lock:
            return deepcopy(self._history)

    def validate(self, proposal: dict, window_id: int | None = None) -> Validation:
        """Valida uma proposta JSON contra a detecção e o estado operacional atual."""
        if not isinstance(proposal, dict) or set(proposal) != {"acao", "parametros", "justificativa"}:
            return Validation("A proposta deve conter ação, parâmetros e justificativa")
        action, parameters, reason = (proposal[key] for key in ("acao", "parametros", "justificativa"))
        if not isinstance(action, str) or action not in ACTION_PARAMETERS:
            return Validation("Ação desconhecida")
        if not isinstance(parameters, dict) or set(parameters) != ACTION_PARAMETERS[action]:
            return Validation("Parâmetros incompatíveis com a ação")
        if not isinstance(reason, str) or not reason.strip():
            return Validation("Justificativa textual obrigatória")
        if window_id is not None and (type(window_id) is not int or window_id not in self._detections):
            return Validation("Identificador de janela inexistente")
        if action == NO_ACTION:
            return Validation("Decisão sem mudança operacional", accepted=True)

        event_id = parameters["evento_id"]
        if not isinstance(event_id, str) or not event_id.strip():
            return Validation("Identificador de evento inválido")
        if action == REGISTER_ALERT:
            return self._validate_alert(event_id, self._detections.get(window_id))
        event = self._state["eventos"].get(event_id)
        if event is None:
            return Validation("Evento inexistente")
        if action == PRIORITIZE:
            priority = parameters["prioridade"]
            if priority not in PRIORITIES:
                return Validation("Prioridade deve ser baixa, normal ou alta")
            return self._validate_target(priority, event["prioridade"])
        if action == INTENSIFY:
            stride = parameters["avanco_registros"]
            if (type(stride) is not int or not self.limits.min_inspection_stride
                    <= stride <= self._state["inspecao"]["avanco_registros"]):
                return Validation("Avanço deve ficar entre o mínimo configurado e o avanço atual")
            return self._validate_target(stride, self._state["inspecao"]["avanco_registros"])
        return self._validate_expansion(parameters["tamanho_registros"], event)

    def _validate_alert(self, event_id, detection) -> Validation:
        if event_id in self._state["alertas"]:
            return Validation("Alerta já registrado para este episódio")
        if (detection is None or detection.get("situacao") != SUSPECT
                or detection.get("novo_alerta") is not True or detection.get("alerta_id") != event_id):
            return Validation("O registro exige um novo episódio suspeito com identificador correspondente")
        window = detection["janela"]
        registers = window.get("registros", ())
        start = self._positions.get(registers[0]) if registers else None
        stats = (detection.get("metricas") or {}).get(THROUGHPUT) or {}
        delta = (detection.get("variacao_relativa_referencia") or {}).get(THROUGHPUT)
        config = detection.get("parametros") or {}
        coverage, min_coverage = stats.get("cobertura"), config.get("min_coverage")
        drop = config.get("throughput_drop")
        confirmations, persistence = detection.get("persistencia_janelas"), config.get("persistence")
        if (start is None or window.get("completa") is not True
                or tuple(self._registers[start:start + len(registers)]) != tuple(registers)
                or not all(type(value) in (int, float) and isfinite(value)
                           for value in (stats.get("mediana"), coverage, min_coverage, delta, drop))
                or not 0 < min_coverage <= coverage <= 1 or not 0 < drop <= 1 or delta > -drop
                or type(confirmations) is not int or type(persistence) is not int
                or not 0 < persistence <= confirmations
                or not (detection.get("referencia") or {}).get("janelas")
                or not detection.get("regra") or not detection.get("justificativa")):
            return Validation("Evidências de janela, cobertura, queda ou persistência insuficientes")
        return Validation("Episódio novo com evidências do detector", accepted=True, changes_state=True)

    @staticmethod
    def _validate_target(requested, current) -> Validation:
        if requested == current:
            return Validation("Estado solicitado já está em vigor", accepted=True)
        return Validation("Parâmetros dentro dos limites", accepted=True, changes_state=True)

    def _validate_expansion(self, size, event) -> Validation:
        analysis = event["analise"]
        current = analysis["tamanho_registros"]
        if type(size) is not int or size < current:
            return Validation("Tamanho deve ser inteiro e pelo menos igual ao tamanho atual")
        if size == current:
            return self._validate_target(size, current)
        if size > self.limits.max_history_size:
            return Validation("Tamanho excede o máximo de análise por evento")
        extra = size - current
        if extra > self.limits.history_budget - self._state["analise"]["registros_adicionais_consultados"]:
            return Validation("Ampliação excede o orçamento restante de registros")
        first = analysis["primeiro_register"]
        position = self._positions[first] - extra
        if position < 0 or self._registers[position] != first - extra:
            return Validation("Histórico anterior contíguo insuficiente")
        return Validation("Há registros anteriores no mesmo segmento e orçamento disponível",
                          accepted=True, changes_state=True)

    def _execute(self, state: dict, action: str, params: dict, detection: dict | None):
        event_id = params["evento_id"]
        if action == REGISTER_ALERT:
            window = detection["janela"]
            state["alertas"][event_id] = {
                "janela_id": window["id"], "regra": detection["regra"],
                "justificativa": detection["justificativa"],
            }
            state["eventos"][event_id] = {
                "janela_id": window["id"],
                "prioridade": "normal",
                "analise": {
                    "tamanho_registros": len(window["registros"]),
                    "primeiro_register": window["registros"][0],
                    "consultas": [],
                },
            }
        elif action == PRIORITIZE:
            state["eventos"][event_id]["prioridade"] = params["prioridade"]
        elif action == EXPAND:
            event = state["eventos"][event_id]
            analysis = event["analise"]
            extra = params["tamanho_registros"] - analysis["tamanho_registros"]
            end = self._positions[analysis["primeiro_register"]]
            registers = self._registers[end - extra:end]
            rows = self._metrics.iloc[end - extra:end]
            coverage = self._detections[event["janela_id"]]["parametros"]["min_coverage"]
            analysis["consultas"].append({
                "registros": registers,
                "quantidade": len(rows),
                "metricas": {name: asdict(summarize_metric(series, coverage)) for name, series in rows.items()},
            })
            analysis["primeiro_register"] = registers[0]
            analysis["tamanho_registros"] = params["tamanho_registros"]
            state["analise"]["registros_adicionais_consultados"] += len(rows)
        elif action == INTENSIFY:
            state["inspecao"]["avanco_registros"] = params["avanco_registros"]

    @staticmethod
    def _verify(before: dict, after: dict, action: str, params: dict, detection: dict | None) -> bool:
        changes = {section for section in before if before[section] != after[section]}
        event_id = params["evento_id"]
        if action == REGISTER_ALERT:
            window = detection["janela"]
            alert = after["alertas"].get(event_id, {})
            event = after["eventos"].get(event_id, {})
            return (changes == {"alertas", "eventos"}
                    and alert == {"janela_id": window["id"], "regra": detection["regra"],
                                  "justificativa": detection["justificativa"]}
                    and event.get("janela_id") == window["id"]
                    and event.get("prioridade") == "normal"
                    and event.get("analise") == {
                        "tamanho_registros": len(window["registros"]),
                        "primeiro_register": window["registros"][0], "consultas": [],
                    }
                    and after["alertas"] == before["alertas"] | {event_id: alert}
                    and after["eventos"] == before["eventos"] | {event_id: event})
        if action == PRIORITIZE:
            expected = before["eventos"][event_id] | {"prioridade": params["prioridade"]}
            return changes == {"eventos"} and after["eventos"] == before["eventos"] | {event_id: expected}
        if action == INTENSIFY:
            return (changes == {"inspecao"}
                    and after["inspecao"]["avanco_registros"] == params["avanco_registros"])
        previous_event = before["eventos"][event_id]
        previous = previous_event["analise"]
        current = after["eventos"][event_id]["analise"]
        extra = params["tamanho_registros"] - previous["tamanho_registros"]
        start = previous["primeiro_register"] - extra
        if not current["consultas"]:
            return False
        query = current["consultas"][-1]
        expected = {
            "tamanho_registros": params["tamanho_registros"],
            "primeiro_register": start,
            "consultas": [*previous["consultas"], query],
        }
        expected_spent = before["analise"]["registros_adicionais_consultados"] + extra
        return (changes == {"eventos", "analise"}
                and after["analise"] == {"registros_adicionais_consultados": expected_spent}
                and after["eventos"] == before["eventos"] | {event_id: previous_event | {"analise": expected}}
                and query["quantidade"] == extra
                and query["registros"] == list(range(start, start + extra))
                and set(query["metricas"]) == set(METRICS)
                and all(stat["validos"] + stat["ausentes"] + stat["invalidos"] == extra
                        for stat in query["metricas"].values()))

    def apply(self, proposal: dict, *, origin: str, window_id: int | None = None) -> dict:
        """Valida, testa a alteração em uma cópia e registra o resultado da proposta."""
        if not isinstance(origin, str) or not origin.strip():
            raise ValueError("Origem da decisão deve ser um texto preenchido")
        with self._lock:
            return self._apply(proposal, origin, window_id)

    def _apply(self, proposal, origin: str, window_id: int | None) -> dict:
        # Normaliza propostas externas para que até as recusadas permaneçam serializáveis.
        try:
            proposal = json.loads(json.dumps(proposal, allow_nan=False))
        except (TypeError, ValueError, OverflowError):
            proposal = None
            validation = Validation("Proposta deve ser serializável como JSON")
        else:
            validation = self.validate(proposal, window_id)
        before = self.state()
        execution = {"estado": "nao_executada", "justificativa": validation.reason}
        verification = {"estado": "nao_aplicavel", "justificativa": "Proposta recusada"}
        record = proposal if isinstance(proposal, dict) else {}
        params = record.get("parametros")
        action = record.get("acao")
        detection = self._detections.get(window_id) if type(window_id) is int else None
        if validation.accepted and not validation.changes_state:
            verification = {"estado": "aprovada", "justificativa": "Estado operacional permaneceu igual"}
        elif validation.accepted:
            candidate = deepcopy(before)
            try:
                self._execute(candidate, action, params, detection)
                if not self._verify(before, candidate, action, params, detection):
                    raise RuntimeError("A alteração observada diverge da ação validada")
                json.dumps(candidate, allow_nan=False)
            except Exception as error:
                reason = f"{type(error).__name__}: {error}"
                execution = {"estado": "falha", "justificativa": reason}
                verification = {"estado": "reprovada", "justificativa": reason}
            else:
                self._state = candidate
                execution = {"estado": "executada", "justificativa": "Alteração aplicada ao simulador"}
                verification = {"estado": "aprovada", "justificativa": "Alteração esperada observada"}
        after = self.state()
        event_id = params.get("evento_id") if isinstance(params, dict) else None
        if not isinstance(event_id, str):
            event_id = detection.get("alerta_id") if detection is not None else None
        entry = {
            "id": len(self._history) + 1,
            "evento_id": event_id,
            "janela_id": window_id if type(window_id) is int else None,
            "origem": origin,
            "proposta": proposal,
            "validacao": {"estado": "aceita" if validation.accepted else "recusada",
                          "justificativa": validation.reason},
            "execucao": execution,
            "estado_anterior": before,
            "estado_posterior": after,
            "alteracoes": {section: {"antes": before[section], "depois": after[section]}
                           for section in before if before[section] != after[section]},
            "verificacao": verification,
        }
        self._history.append(entry)
        return deepcopy(entry)
