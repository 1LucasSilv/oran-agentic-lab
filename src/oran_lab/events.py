"""Instrumentação opcional do fluxo operacional."""

from contextlib import contextmanager
from time import perf_counter


@contextmanager
def stage(emit, component, **initial):
    if emit is None:
        yield {}
        return
    start = perf_counter()
    outcome = {}
    emit(component, "iniciada", initial)
    try:
        yield outcome
    except Exception as error:
        emit(component, "falha", {**initial, "erro": str(error), "tempo_s": perf_counter() - start})
        raise
    else:
        status = outcome.pop("estado", "concluida")
        emit(component, status, {**initial, **outcome, "tempo_s": perf_counter() - start})
