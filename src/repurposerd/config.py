"""Caricamento della configurazione e percorsi del progetto."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


def project_root() -> Path:
    """Radice del repo: risale da questo file fino a trovare pyproject.toml."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return here.parents[2]


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def raw(self) -> Path:
        return self.root / "data" / "raw"

    @property
    def processed(self) -> Path:
        return self.root / "data" / "processed"

    @property
    def db(self) -> Path:
        return self.processed / "repurposerd.duckdb"

    @property
    def manifest(self) -> Path:
        return self.raw / "manifest.json"

    @property
    def out(self) -> Path:
        return self.root / "out"

    def ensure(self) -> None:
        for p in (self.raw, self.processed, self.out):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def paths() -> Paths:
    return Paths(project_root())


def _load_yaml(name: str) -> dict[str, Any]:
    path = paths().config / name
    if not path.exists():
        raise FileNotFoundError(f"Configurazione mancante: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=1)
def sources_config() -> dict[str, Any]:
    return _load_yaml("sources.yaml")


@lru_cache(maxsize=1)
def scoring_config() -> dict[str, Any]:
    return _load_yaml("scoring.yaml")


@lru_cache(maxsize=1)
def mechanism_config() -> dict[str, Any]:
    return _load_yaml("mechanism.yaml")


def config_digest() -> str:
    """Impronta di cio' che determina il risultato: configurazione E versione.

    Finisce nell'evidence bundle e in ogni report, dove serve a dire se due
    documenti siano confrontabili.

    PERCHE' C'E' ANCHE LA VERSIONE
    Per un periodo l'impronta copriva solo i file di configurazione. Poi il
    meccanismo di malattia ha iniziato a essere derivato anche da Orphanet
    invece che solo da `config/mechanism.yaml`: una modifica di **codice**, che
    cambia i risultati lasciando i file di configurazione identici. Due report
    con la stessa impronta sarebbero apparsi confrontabili senza esserlo, che
    e' peggio di non avere l'impronta.

    Resta un limite dichiarato: la versione cambia a ogni rilascio, non a ogni
    commit. Fra due modifiche non rilasciate l'impronta puo' coincidere pur
    coprendo comportamenti diversi. Chi confronta report prodotti da copie di
    lavoro diverse deve verificarlo per conto proprio.
    """
    from . import __version__

    payload = json.dumps(
        {
            "scoring": scoring_config(),
            "mechanism": mechanism_config(),
            "version": __version__,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
