"""Serializzazione JSON delle dataclass di dominio.

Sostituisce `model_dump_json` e la costruzione da dizionario che pydantic
offriva. Serve in tre punti: l'evidence bundle esportato con `--bundle-out`, e
le cache su disco di PubMed e openFDA.

E' deliberatamente piccola e senza dipendenze. L'alternativa sarebbe stata
un'altra libreria di serializzazione, cioe' sostituire una dipendenza con
un'altra dopo aver appena tolto pydantic perche' una dipendenza nativa non
firmata rendeva il progetto ineseguibile su Windows.
"""

from __future__ import annotations

import types
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Union, get_args, get_origin, get_type_hints


def to_jsonable(obj: Any) -> Any:
    """Converte dataclass, enum, date e collezioni in strutture serializzabili.

    Le `set` diventano liste ordinate: JSON non ha gli insiemi, e l'ordinamento
    rende il risultato riproducibile fra esecuzioni, che e' una proprieta' che
    questo progetto dichiara nei report.
    """
    if obj is None or isinstance(obj, str | int | float | bool):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, set | frozenset):
        return sorted(to_jsonable(v) for v in obj)
    if isinstance(obj, list | tuple):
        return [to_jsonable(v) for v in obj]
    return str(obj)


def _unwrap_optional(tp: Any) -> Any:
    """Da `X | None` a `X`. Lascia intatto tutto il resto."""
    origin = get_origin(tp)
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return tp


def _coerce(tp: Any, value: Any) -> Any:
    if value is None:
        return None

    tp = _unwrap_optional(tp)
    origin = get_origin(tp)

    if origin in (list, set, frozenset, tuple):
        args = get_args(tp)
        inner = args[0] if args else Any
        items = [_coerce(inner, v) for v in value]
        return set(items) if origin in (set, frozenset) else items
    if origin is dict:
        return dict(value)

    if is_dataclass(tp) and isinstance(tp, type):
        return from_jsonable(tp, value)
    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp(value)
    if tp is datetime:
        return datetime.fromisoformat(value)
    if tp is date:
        return date.fromisoformat(value)
    return value


def from_jsonable(cls: type, data: dict[str, Any]) -> Any:
    """Ricostruisce una dataclass da un dizionario prodotto da `to_jsonable`.

    I campi assenti nel dizionario restano al loro default: le cache su disco
    sopravvivono cosi' all'aggiunta di un campo nuovo, invece di dover essere
    invalidate a ogni modifica del modello.
    """
    hints = get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        if f.name in data:
            kwargs[f.name] = _coerce(hints.get(f.name, Any), data[f.name])
    return cls(**kwargs)
