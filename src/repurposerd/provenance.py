"""Manifest dei download: versione, data di accesso, checksum, licenza.

Il repo non ridistribuisce dati. Questo modulo e' cio' che rende comunque
riproducibile un run: dice esattamente quale versione di quale fonte e' stata
usata e quando, e permette di verificare che il file non sia cambiato sotto i piedi.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import paths, sources_config
from .models import Provenance


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def load_manifest() -> dict[str, Any]:
    mpath = paths().manifest
    if not mpath.exists():
        return {"entries": {}}
    with mpath.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_manifest(manifest: dict[str, Any]) -> None:
    mpath = paths().manifest
    mpath.parent.mkdir(parents=True, exist_ok=True)
    with mpath.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False, sort_keys=True)


def record_download(
    source_id: str,
    file_id: str,
    url: str,
    local_path: Path,
    version: str | None = None,
) -> dict[str, Any]:
    src = sources_config()["sources"][source_id]
    entry = {
        "source_id": source_id,
        "source_name": src["name"],
        "license": src["license"],
        "url": url,
        "filename": local_path.name,
        "bytes": local_path.stat().st_size,
        "sha256": sha256_of(local_path),
        "version": version,
        "accessed_at": datetime.now().date().isoformat(),
    }
    manifest = load_manifest()
    manifest.setdefault("entries", {})[f"{source_id}:{file_id}"] = entry
    save_manifest(manifest)
    return entry


def provenance_for(
    source_id: str, file_id: str | None = None, record_id: str | None = None
) -> Provenance:
    """Costruisce la Provenance di un fatto, arricchita col manifest se disponibile."""
    src = sources_config()["sources"][source_id]
    entry: dict[str, Any] = {}
    if file_id:
        entry = load_manifest().get("entries", {}).get(f"{source_id}:{file_id}", {})

    accessed = entry.get("accessed_at")
    return Provenance(
        source_id=source_id,
        source_name=src["name"],
        license=src["license"],
        url=entry.get("url") or src.get("homepage"),
        version=entry.get("version"),
        accessed_at=date.fromisoformat(accessed) if accessed else None,
        record_id=record_id,
    )


def missing_sources(required: list[tuple[str, str]]) -> list[str]:
    """Ritorna le chiavi fonte:file non ancora scaricate."""
    entries = load_manifest().get("entries", {})
    out = []
    for source_id, file_id in required:
        key = f"{source_id}:{file_id}"
        if key not in entries:
            out.append(key)
            continue
        local = paths().raw / entries[key]["filename"]
        if not local.exists():
            out.append(key)
    return out
