"""Interfaccia a riga di comando di RepurposeRD."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import paths, sources_config
from .llm.backend import make_backend
from .llm.narrate import narrate_bundle
from .llm.validator import load_vocabularies
from .pipeline.bundle import build_bundle
from .pipeline.resolve import AmbiguousDisease, DiseaseNotFound, resolve
from .provenance import load_manifest, missing_sources
from .report.render import render_report
from .serialize import to_jsonable
from .store import is_built, session

app = typer.Typer(
    add_completion=False,
    help="Generatore di ipotesi di drug repurposing per malattie rare monogeniche. "
    "Ipotesi di ricerca computazionali, non consigli medici.",
)
console = Console()


def _require_store() -> None:
    if not paths().db.exists():
        console.print(
            "[red]Store non trovato.[/red] Esegui prima:\n  repurposerd fetch\n  repurposerd build"
        )
        raise typer.Exit(1)
    with session(read_only=True) as con:
        if not is_built(con):
            console.print("[red]Store incompleto.[/red] Esegui: repurposerd build")
            raise typer.Exit(1)


# ---------------------------------------------------------------- fetch


@app.command()
def fetch(
    force: bool = typer.Option(False, "--force", help="Riscarica anche i file gia' presenti."),
    only: list[str] = typer.Option(None, "--only", help="Limita a queste fonti."),
) -> None:
    """Scarica le fonti aperte in locale, registrando licenza e checksum."""
    from .sources.fetch import fetch_all

    paths().ensure()
    console.print("[bold]Download delle fonti aperte[/bold]\n")
    fetch_all(force=force, only=list(only) if only else None)
    console.print(f"\n[green]Fatto.[/green] Manifest: {paths().manifest}")


# ---------------------------------------------------------------- build


@app.command()
def build(only: list[str] = typer.Option(None, "--only", help="Limita a queste fonti.")) -> None:
    """Costruisce lo store DuckDB dai file grezzi."""
    from .sources.build import build as run_build

    console.print("[bold]Costruzione dello store[/bold]\n")
    run_build(only=list(only) if only else None)
    console.print(f"\n[green]Fatto.[/green] Store: {paths().db}")


# ---------------------------------------------------------------- sources


@app.command()
def sources() -> None:
    """Elenca le fonti dati, le licenze e lo stato di download."""
    cfg = sources_config()
    entries = load_manifest().get("entries", {})

    table = Table(title="Fonti dati", show_lines=False)
    table.add_column("Fonte")
    table.add_column("Ruolo", max_width=42)
    table.add_column("Licenza", max_width=22)
    table.add_column("Stato")

    for source_id, spec in cfg["sources"].items():
        files = spec.get("files") or []
        if files:
            have = sum(1 for f in files if f"{source_id}:{f['id']}" in entries)
            status = (
                f"[green]{have}/{len(files)}[/green]"
                if have == len(files)
                else f"[yellow]{have}/{len(files)}[/yellow]"
            )
        else:
            status = "[dim]API[/dim]"
        table.add_row(spec["name"], spec.get("role", ""), spec["license"], status)

    console.print(table)

    console.print("\n[bold]Escluse deliberatamente[/bold]")
    for ex in cfg.get("excluded", []):
        console.print(f"  [red]x[/red] [bold]{ex['name']}[/bold]: {' '.join(ex['reason'].split())}")


# ---------------------------------------------------------------- resolve


@app.command()
def resolve_cmd(
    query: str = typer.Argument(..., help="Nome o identificatore della malattia."),
) -> None:
    """Risolve una malattia al suo identificatore Mondo e ai geni causali."""
    _require_store()
    with session(read_only=True) as con:
        try:
            r = resolve(con, query)
        except (DiseaseNotFound, AmbiguousDisease) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

    console.print(f"[bold]{r.disease.label}[/bold]  ({r.disease.mondo_id})")
    if r.disease.orpha_codes:
        console.print(f"  Orphanet: {', '.join(r.disease.orpha_codes)}")
    if r.disease.omim_ids:
        console.print(f"  OMIM: {', '.join(r.disease.omim_ids)}")
    console.print("\n  [bold]Geni causali[/bold] (associazioni curate Orphanet):")
    if not r.causal_genes:
        console.print("    [yellow]nessuno[/yellow]")
    for cg in r.causal_genes:
        pmids = f"  PMID: {', '.join(cg.validation_pmids)}" if cg.validation_pmids else ""
        console.print(f"    [bold]{cg.gene.symbol}[/bold]  ({cg.association_type}){pmids}")


app.command(name="resolve")(resolve_cmd)


# ---------------------------------------------------------------- run


@app.command()
def run(
    query: str = typer.Argument(..., help="Nome o identificatore della malattia."),
    out: Path = typer.Option(None, "--out", "-o", help="File Markdown di destinazione."),
    top: int = typer.Option(15, "--top", "-n", help="Numero massimo di candidati."),
    llm_backend: str = typer.Option(
        "ollama", "--llm-backend", help="ollama | openai-compatible | template"
    ),
    model: str = typer.Option(None, "--model", help="Nome del modello locale."),
    host: str = typer.Option(None, "--host", help="Endpoint del backend LLM."),
    narrate_top: int = typer.Option(
        None,
        "--narrate-top",
        help="Genera la prosa con il modello solo per i primi N candidati; "
        "per i restanti usa il generatore deterministico. Rende praticabile "
        "un modello grande su report lunghi.",
    ),
    llm_timeout: float = typer.Option(
        None,
        "--llm-timeout",
        help="Secondi di attesa per generazione. Su CPU lente servono valori alti.",
    ),
    no_literature: bool = typer.Option(
        False, "--no-literature", help="Salta le interrogazioni PubMed (piu' rapido, offline)."
    ),
    no_regulatory: bool = typer.Option(
        False,
        "--no-regulatory",
        help="Salta la conferma FDA via openFDA (piu' rapido, offline).",
    ),
    shuffle_control: bool = typer.Option(
        False, "--shuffle-control", help="Controllo negativo: gene causale casuale."
    ),
    no_phenotype_bridge: bool = typer.Option(
        False,
        "--no-phenotype-bridge",
        help="Disattiva il ramo fenotipico e usa solo il percorso meccanicistico.",
    ),
    max_bridges: int = typer.Option(
        None,
        "--max-bridges",
        help="Quante malattie fenotipicamente simili usare come punto di ingresso.",
    ),
    seed: int = typer.Option(0, "--seed", help="Seme del controllo negativo."),
    bundle_out: Path = typer.Option(
        None, "--bundle-out", help="Salva anche l'evidence bundle in JSON."
    ),
) -> None:
    """Genera le ipotesi di riposizionamento e produce il report."""
    _require_store()

    console.print(f"[bold]RepurposeRD[/bold] — {query}\n")
    with session(read_only=True) as con:
        try:
            bundle = build_bundle(
                con,
                query,
                top_n=top,
                with_literature=not no_literature,
                shuffle_control=shuffle_control,
                seed=seed,
                use_phenotype_bridge=not no_phenotype_bridge,
                max_bridges=max_bridges,
                with_regulatory=not no_regulatory,
            )
        except (DiseaseNotFound, AmbiguousDisease, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

        known_genes, known_drugs = load_vocabularies(con)

    console.print("\n  generazione delle spiegazioni ...")
    backend = make_backend(llm_backend, model=model, host=host, timeout=llm_timeout)
    narration = narrate_bundle(bundle, backend, known_genes, known_drugs, narrate_top=narrate_top)
    console.print(f"  [dim]{narration.note()}[/dim]")

    markdown = render_report(bundle, narration)

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        console.print(f"\n[green]Report scritto:[/green] {out}")
    else:
        sys.stdout.write(markdown)

    if bundle_out:
        bundle_out.parent.mkdir(parents=True, exist_ok=True)
        bundle_out.write_text(
            json.dumps(to_jsonable(bundle), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        console.print(f"[green]Evidence bundle:[/green] {bundle_out}")


# ---------------------------------------------------------------- benchmark


@app.command()
def benchmark(
    out: Path = typer.Option(None, "--out", "-o", help="File Markdown di destinazione."),
    top: int = typer.Option(40, "--top", "-n", help="Candidati esaminati per caso."),
    quick: bool = typer.Option(
        False,
        "--quick",
        help="Salta PubMed. Molto piu' rapido, ma sottostima la copertura: "
        "alcuni riposizionamenti noti emergono proprio grazie alla letteratura.",
    ),
    no_phenotype_bridge: bool = typer.Option(
        False, "--no-phenotype-bridge", help="Esegue il banco senza il ramo fenotipico."
    ),
    only: list[str] = typer.Option(
        None, "--only", help="Esegue solo questi identificativi di caso."
    ),
) -> None:
    """Esegue il banco di prova sui riposizionamenti noti e misura la copertura."""
    _require_store()

    from .benchmark import run_benchmark
    from .report.benchmark_render import render_benchmark

    console.print("[bold]Banco di prova[/bold]")
    if quick:
        console.print(
            "  [yellow]modalita' rapida: la letteratura non viene interrogata, "
            "la copertura misurata sara' inferiore a quella reale[/yellow]"
        )

    def progress(i: int, total: int, case: dict) -> None:
        console.print(f"\n[dim]({i}/{total})[/dim] [bold]{case['id']}[/bold] — {case['disease']}")

    with session(read_only=True) as con:
        report = run_benchmark(
            con,
            top_n=top,
            with_literature=not quick,
            use_phenotype_bridge=not no_phenotype_bridge,
            only=list(only) if only else None,
            progress=progress,
        )

    hit, tot = report.recall_at(top)
    console.print(f"\n[bold]Copertura entro la posizione {top}: {hit}/{tot}[/bold]")
    for r in report.results:
        if r.error:
            console.print(f"  [red]errore[/red] {r.case_id}: {r.error}")

    markdown = render_benchmark(report)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        console.print(f"[green]Report scritto:[/green] {out}")
    else:
        sys.stdout.write(markdown)


# ---------------------------------------------------------------- doctor


@app.command()
def doctor() -> None:
    """Verifica che tutto sia pronto e dice cosa fare per cio' che manca.

    Esiste perche' il primo ostacolo di chi installa questo strumento non e' il
    codice ma la catena di prerequisiti: scaricare 180 MB di fonti, costruire lo
    store, avere o non avere un modello locale. Scoprirli uno alla volta da
    messaggi di errore a meta' pipeline e' un modo pessimo di conoscere un
    progetto.
    """
    from .sources.build import REQUIRED_FILES
    from .store import table_counts

    problemi: list[str] = []
    console.print("[bold]Verifica dell'ambiente[/bold]\n")

    # --- Python
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if sys.version_info < (3, 11) or sys.version_info >= (3, 14):
        console.print(f"  [red]x[/red] Python {version} — servono 3.11, 3.12 o 3.13")
        problemi.append("usa una versione di Python fra 3.11 e 3.13")
    else:
        console.print(f"  [green]v[/green] Python {version}")

    # --- configurazione
    try:
        from .config import config_digest, scoring_config

        scoring_config()
        console.print(f"  [green]v[/green] configurazione leggibile (impronta {config_digest()})")
    except Exception as exc:
        console.print(f"  [red]x[/red] configurazione illeggibile: {exc}")
        problemi.append("controlla i file in config/")

    # --- fonti scaricate
    mancanti = missing_sources(REQUIRED_FILES)
    if mancanti:
        console.print(f"  [red]x[/red] {len(mancanti)} file di fonti mancanti")
        for chiave in mancanti[:4]:
            console.print(f"      [dim]{chiave}[/dim]")
        problemi.append("esegui: repurposerd fetch")
    else:
        console.print(f"  [green]v[/green] {len(REQUIRED_FILES)} file di fonti presenti")

    # --- store
    if not paths().db.exists():
        console.print("  [red]x[/red] store DuckDB assente")
        problemi.append("esegui: repurposerd build")
    else:
        with session(read_only=True) as con:
            counts = table_counts(con)
        vuote = [t for t, n in counts.items() if n == 0]
        if vuote:
            console.print(f"  [yellow]![/yellow] store incompleto: {len(vuote)} tabelle vuote")
            console.print(f"      [dim]{', '.join(vuote[:5])}[/dim]")
            problemi.append("esegui: repurposerd build")
        else:
            righe = sum(counts.values())
            console.print(
                f"  [green]v[/green] store popolato ({righe:,} righe in {len(counts)} tabelle)"
            )

    # --- modello locale, opzionale
    backend = make_backend("ollama")
    if backend.available():
        console.print(f"  [green]v[/green] modello locale raggiungibile ({backend.describe()})")
    else:
        console.print("  [dim]-[/dim] nessun modello locale raggiungibile")
        console.print(
            "      [dim]non e' un problema: il generatore deterministico funziona sempre "
            "(--llm-backend template)[/dim]"
        )

    # --- rete, opzionale ma influisce sul punteggio
    try:
        import httpx

        httpx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi", timeout=8.0)
        console.print("  [green]v[/green] PubMed raggiungibile")
    except Exception:
        console.print("  [yellow]![/yellow] PubMed non raggiungibile")
        console.print(
            "      [dim]la pipeline funziona con --no-literature, ma la componente di "
            "letteratura varra' zero per tutti i candidati[/dim]"
        )

    console.print()
    if problemi:
        console.print("[bold yellow]Cosa fare[/bold yellow]")
        for passo in dict.fromkeys(problemi):
            console.print(f"  {passo}")
        raise typer.Exit(1)

    console.print("[bold green]Tutto pronto.[/bold green] Prova con:")
    console.print('  repurposerd run "tuberous sclerosis" --llm-backend template')


# ---------------------------------------------------------------- info


@app.command()
def info() -> None:
    """Stato dello store e della configurazione."""
    from .config import config_digest
    from .store import table_counts

    console.print(f"Radice progetto : {paths().root}")
    console.print(
        f"Store           : {paths().db} "
        f"({'presente' if paths().db.exists() else '[red]assente[/red]'})"
    )
    console.print(f"Impronta config : {config_digest()}")

    if paths().db.exists():
        with session(read_only=True) as con:
            console.print("\n[bold]Tabelle[/bold]")
            for table, n in table_counts(con).items():
                console.print(f"  {table:26} {n:>10,}")

    entries = load_manifest().get("entries", {})
    if entries:
        console.print("\n[bold]File scaricati[/bold]")
        for key, e in sorted(entries.items()):
            console.print(f"  {key:44} {e['bytes'] / 1e6:>7.1f} MB  {e['accessed_at']}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
