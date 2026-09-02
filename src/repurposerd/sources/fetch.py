"""Download delle fonti in locale, con registrazione nel manifest.

Il repo distribuisce codice, mai dati: e' questo modulo che porta le fonti sul
disco dell'utente, tracciando licenza, versione e checksum di ognuna.
"""

from __future__ import annotations

from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TransferSpeedColumn

from ..config import paths, sources_config
from ..provenance import record_download

console = Console()

USER_AGENT = "RepurposeRD/0.1 (open-source research tool; +https://github.com/OWNER/repurposerd)"


def iter_source_files() -> list[tuple[str, dict]]:
    """Tutte le coppie (source_id, file_spec) delle fonti scaricabili come file."""
    out = []
    for source_id, spec in sources_config()["sources"].items():
        for file_spec in spec.get("files", []) or []:
            out.append((source_id, file_spec))
    return out


def fetch_file(source_id: str, file_spec: dict, force: bool = False) -> Path:
    dest = paths().raw / file_spec["filename"]
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and not force:
        console.print(f"  [dim]gia' presente:[/dim] {dest.name}")
        return dest

    url = file_spec["url"]
    tmp = dest.with_suffix(dest.suffix + ".part")

    with httpx.stream(
        "GET", url, follow_redirects=True, timeout=120.0, headers={"User-Agent": USER_AGENT}
    ) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0)) or None
        with Progress(
            TextColumn("  [cyan]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(file_spec["filename"], total=total)
            with tmp.open("wb") as fh:
                for chunk in resp.iter_bytes(1 << 16):
                    fh.write(chunk)
                    progress.update(task, advance=len(chunk))

    tmp.replace(dest)
    entry = record_download(source_id, file_spec["id"], url, dest)
    console.print(
        f"  [green]scaricato[/green] {dest.name} "
        f"([dim]{entry['bytes'] / 1e6:.1f} MB, licenza {entry['license']}[/dim])"
    )
    return dest


def fetch_all(force: bool = False, only: list[str] | None = None) -> list[Path]:
    downloaded = []
    for source_id, file_spec in iter_source_files():
        if only and source_id not in only:
            continue
        console.print(f"[bold]{source_id}[/bold] / {file_spec['id']}")
        downloaded.append(fetch_file(source_id, file_spec, force=force))
    return downloaded
