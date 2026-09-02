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
    """Hash stabile della configurazione che influenza il risultato.

    Finisce nell'evidence bundle e nel report: due run con digest diverso non
    sono confrontabili, e il lettore deve poterlo vedere.
    """
    payload = json.dumps(
        {"scoring": scoring_config(), "mechanism": mechanism_config()},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
