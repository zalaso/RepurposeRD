"""ETL: dai file grezzi allo store DuckDB normalizzato.

STRATEGIA DI CARICAMENTO
Per i file tabellari (HGNC, Reactome, DGIdb) si usa il lettore CSV nativo di
DuckDB invece di iterare in Python: il file viene letto dal motore, in C++, con
un ordine di grandezza di differenza sui 94 MB di NCBI2Reactome. I parser Python
in `parsers.py` restano la definizione leggibile del formato e sono cio' che i
test usano; qui si carica, li' si documenta.

Per OBO (Mondo) e XML (Orphanet) non esiste un lettore nativo, e il parser
Python e' anche il caricatore.

Ogni loader e' idempotente: svuota le proprie tabelle e le ricostruisce, cosi'
un ETL interrotto non lascia duplicati silenziosi.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
from rich.console import Console

from ..config import paths
from ..provenance import load_manifest
from ..store import bulk_insert, create_indexes, session, table_counts, truncate
from . import parsers

console = Console(file=sys.stdout)

# Coppie (source_id, file_id) necessarie alla pipeline di fase 1.
REQUIRED_FILES: list[tuple[str, str]] = [
    ("hgnc", "hgnc_complete_set"),
    ("mondo", "mondo_rare_obo"),
    ("orphanet", "orphanet_gene_associations"),
    ("reactome", "reactome_gene_to_pathway"),
    ("reactome", "reactome_pathway_relations"),
    ("reactome", "reactome_pathways"),
    ("dgidb", "dgidb_interactions"),
    ("hpo", "hpo_obo"),
    ("hpo", "hpo_disease_annotations"),
]


def _raw_path(source_id: str, file_id: str) -> Path:
    entry = load_manifest().get("entries", {}).get(f"{source_id}:{file_id}")
    if not entry:
        raise FileNotFoundError(
            f"'{source_id}:{file_id}' non risulta scaricato. Esegui prima: repurposerd fetch"
        )
    path = paths().raw / entry["filename"]
    if not path.exists():
        raise FileNotFoundError(
            f"File assente sul disco: {path}. Esegui: repurposerd fetch --force"
        )
    return path


def _posix(path: Path) -> str:
    """DuckDB accetta i backslash di Windows, ma le forward slash evitano ogni
    ambiguita' di escaping nelle stringhe SQL."""
    return path.resolve().as_posix()


# ---------------------------------------------------------------- HGNC


def load_hgnc(con: duckdb.DuckDBPyConnection) -> int:
    path = _raw_path("hgnc", "hgnc_complete_set")
    truncate(con, "genes")
    con.execute(
        f"""
        INSERT INTO genes
            (symbol, hgnc_id, entrez_id, uniprot_ids, name, prev_symbols, alias_symbols)
        SELECT symbol, hgnc_id, entrez_id, uniprot_ids, name, prev_symbol, alias_symbol
        FROM (
            SELECT
                upper(trim(symbol))                       AS symbol,
                nullif(trim(hgnc_id), '')                 AS hgnc_id,
                try_cast(nullif(trim(entrez_id), '') AS BIGINT) AS entrez_id,
                nullif(trim(uniprot_ids), '')             AS uniprot_ids,
                nullif(trim(name), '')                    AS name,
                nullif(trim(prev_symbol), '')             AS prev_symbol,
                nullif(trim(alias_symbol), '')            AS alias_symbol,
                row_number() OVER (PARTITION BY upper(trim(symbol))) AS rn
            FROM read_csv('{_posix(path)}', delim='\t', header=true, quote='',
                          all_varchar=true, ignore_errors=true)
            WHERE trim(status) = 'Approved' AND nullif(trim(symbol), '') IS NOT NULL
        )
        WHERE rn = 1
        """
    )
    return con.execute("SELECT count(*) FROM genes").fetchone()[0]


# ---------------------------------------------------------------- Mondo (OBO)


def load_mondo(con: duckdb.DuckDBPyConnection) -> int:
    path = _raw_path("mondo", "mondo_rare_obo")
    truncate(con, "diseases", "disease_synonyms", "disease_xrefs", "disease_is_a")

    terms: list[dict] = []
    synonyms: list[dict] = []
    xrefs: list[dict] = []
    parents: list[dict] = []
    seen: set[str] = set()

    for term in parsers.parse_mondo_obo(path):
        mid = term["mondo_id"]
        if mid in seen:
            continue
        seen.add(mid)
        terms.append({"mondo_id": mid, "name": term["name"], "definition": term.get("definition")})
        synonyms.extend({"mondo_id": mid, "synonym": s} for s in term["synonyms"])
        xrefs.extend({"mondo_id": mid, "xref": x} for x in term["xrefs"])
        parents.extend({"child_id": mid, "parent_id": p} for p in term.get("parents", []))

    n = bulk_insert(con, "diseases", terms)
    bulk_insert(con, "disease_synonyms", synonyms)
    bulk_insert(con, "disease_xrefs", xrefs)
    bulk_insert(con, "disease_is_a", parents)
    return n


# ---------------------------------------------------------------- Orphanet (XML)


def load_orphanet(con: duckdb.DuckDBPyConnection) -> int:
    path = _raw_path("orphanet", "orphanet_gene_associations")
    truncate(con, "orphanet_gene_assoc")
    return bulk_insert(con, "orphanet_gene_assoc", parsers.parse_orphanet_gene_associations(path))


# ---------------------------------------------------------------- Reactome


def load_reactome(con: duckdb.DuckDBPyConnection) -> int:
    gp = _raw_path("reactome", "reactome_gene_to_pathway")
    rel = _raw_path("reactome", "reactome_pathway_relations")
    pw = _raw_path("reactome", "reactome_pathways")

    truncate(con, "reactome_gene_pathway", "reactome_relations", "reactome_pathways")

    # NCBI2Reactome_All_Levels.txt: nessun header.
    # colonne: entrez, pathway_id, url, pathway_name, evidence_code, species
    con.execute(
        f"""
        INSERT INTO reactome_gene_pathway (entrez_id, pathway_id, pathway_name, evidence_code)
        SELECT try_cast(trim(column0) AS BIGINT), trim(column1), trim(column3), trim(column4)
        FROM read_csv('{_posix(gp)}', delim='\t', header=false, quote='',
                      all_varchar=true, ignore_errors=true, columns={{
                          'column0':'VARCHAR','column1':'VARCHAR','column2':'VARCHAR',
                          'column3':'VARCHAR','column4':'VARCHAR','column5':'VARCHAR'}})
        WHERE trim(column5) = 'Homo sapiens'
          AND try_cast(trim(column0) AS BIGINT) IS NOT NULL
        """
    )

    # ReactomePathwaysRelation.txt: parent <tab> child, tutte le specie.
    con.execute(
        f"""
        INSERT INTO reactome_relations (parent_id, child_id)
        SELECT trim(column0), trim(column1)
        FROM read_csv('{_posix(rel)}', delim='\t', header=false, quote='',
                      all_varchar=true, ignore_errors=true, columns={{
                          'column0':'VARCHAR','column1':'VARCHAR'}})
        WHERE trim(column0) LIKE 'R-HSA-%' AND trim(column1) LIKE 'R-HSA-%'
        """
    )

    # ReactomePathways.txt: id <tab> nome <tab> specie.
    con.execute(
        f"""
        INSERT INTO reactome_pathways (pathway_id, pathway_name)
        SELECT pathway_id, pathway_name FROM (
            SELECT trim(column0) AS pathway_id, trim(column1) AS pathway_name,
                   row_number() OVER (PARTITION BY trim(column0)) AS rn
            FROM read_csv('{_posix(pw)}', delim='\t', header=false, quote='',
                          all_varchar=true, ignore_errors=true, columns={{
                              'column0':'VARCHAR','column1':'VARCHAR','column2':'VARCHAR'}})
            WHERE trim(column2) = 'Homo sapiens'
        ) WHERE rn = 1
        """
    )
    return con.execute("SELECT count(*) FROM reactome_gene_pathway").fetchone()[0]


# ---------------------------------------------------------------- DGIdb


def load_dgidb(con: duckdb.DuckDBPyConnection) -> int:
    path = _raw_path("dgidb", "dgidb_interactions")
    truncate(con, "dgidb_interactions")
    con.execute(
        f"""
        INSERT INTO dgidb_interactions
            (gene_symbol, gene_concept_id, drug_name, drug_concept_id,
             interaction_type, interaction_score, source_db, approved)
        SELECT
            upper(trim(gene_name)),
            nullif(trim(gene_concept_id), ''),
            trim(drug_name),
            nullif(trim(drug_concept_id), ''),
            nullif(lower(nullif(trim(interaction_type), 'NULL')), ''),
            try_cast(nullif(trim(interaction_score), 'NULL') AS DOUBLE),
            nullif(trim(interaction_source_db_name), ''),
            upper(trim(approved)) = 'TRUE'
        FROM read_csv('{_posix(path)}', delim='\t', header=true, quote='',
                      all_varchar=true, ignore_errors=true)
        WHERE nullif(trim(gene_name), '') IS NOT NULL
          AND nullif(trim(drug_name), '') IS NOT NULL
        """
    )
    return con.execute("SELECT count(*) FROM dgidb_interactions").fetchone()[0]


# ---------------------------------------------------------------- HPO


def load_hpo(con: duckdb.DuckDBPyConnection) -> int:
    """Ontologia dei fenotipi e annotazioni malattia -> fenotipo.

    L'ontologia (OBO) passa dal parser Python; le annotazioni (TSV) passano dal
    lettore CSV nativo, come le altre fonti tabellari.
    """
    obo = _raw_path("hpo", "hpo_obo")
    hpoa = _raw_path("hpo", "hpo_disease_annotations")

    truncate(con, "hpo_terms", "hpo_is_a", "disease_phenotypes")

    terms: list[dict] = []
    parents: list[dict] = []
    seen: set[str] = set()
    for term in parsers.parse_hpo_obo(obo):
        hid = term["hpo_id"]
        if hid in seen:
            continue
        seen.add(hid)
        terms.append({"hpo_id": hid, "name": term["name"]})
        parents.extend({"child_id": hid, "parent_id": p} for p in term.get("parents", []))

    bulk_insert(con, "hpo_terms", terms)
    bulk_insert(con, "hpo_is_a", parents)
    n = bulk_insert(con, "disease_phenotypes", parsers.parse_phenotype_hpoa(hpoa))

    _build_phenotype_derivatives(con)
    return n


def _build_phenotype_derivatives(con: duckdb.DuckDBPyConnection) -> None:
    """Calcola chiusura per transitivita' e contenuto informativo dei termini HPO.

    REGOLA DEL TRUE-PATH
    Una malattia annotata con "atassia cerebellare" e' implicitamente annotata
    anche con "atassia" e con "anomalia del sistema nervoso". Espandere le
    annotazioni ai loro antenati e' cio' che rende confrontabili due malattie
    curate a livelli di dettaglio diversi: senza, due malattie descritte con
    termini vicini ma non identici risulterebbero del tutto dissimili.

    CONTENUTO INFORMATIVO
    IC(t) = -log(numero di malattie con t nella chiusura / numero totale).
    Un termine raro porta molta informazione, uno generico quasi nessuna:
    "anomalia del sistema nervoso" e' condiviso da meta' delle malattie rare e
    non dice nulla, "fibre di Rosenthal" ne identifica una manciata. Pesare per
    IC evita che due malattie sembrino simili perche' condividono banalita'.
    """
    import math

    edges = con.execute("SELECT child_id, parent_id FROM hpo_is_a").fetchall()
    parents_of: dict[str, list[str]] = {}
    for child, parent in edges:
        parents_of.setdefault(child, []).append(parent)

    ancestor_cache: dict[str, set[str]] = {}

    def ancestors(term: str) -> set[str]:
        """Antenati del termine, se stesso incluso. Memoizzato.

        L'iterazione e' esplicita invece che ricorsiva perche' HPO ha catene
        profonde e la ricorsione supererebbe il limite di stack di Python.
        """
        if term in ancestor_cache:
            return ancestor_cache[term]
        out: set[str] = set()
        stack = [term]
        while stack:
            node = stack.pop()
            if node in out:
                continue
            out.add(node)
            if node in ancestor_cache:
                out |= ancestor_cache[node]
                continue
            stack.extend(parents_of.get(node, ()))
        ancestor_cache[term] = out
        return out

    annotations = con.execute(
        "SELECT disease_id, any_value(disease_name), list(DISTINCT hpo_id) "
        "FROM disease_phenotypes GROUP BY disease_id"
    ).fetchall()

    truncate(con, "disease_phenotype_closure", "hpo_term_ic", "disease_phenotype_weight")

    closures: dict[str, set[str]] = {}
    names: dict[str, str | None] = {}
    for disease_id, disease_name, terms in annotations:
        closure: set[str] = set()
        for t in terms or []:
            closure |= ancestors(t)
        if closure:
            closures[disease_id] = closure
            names[disease_id] = disease_name

    total_diseases = len(closures)
    if not total_diseases:
        return

    term_freq: dict[str, int] = {}
    for closure in closures.values():
        for t in closure:
            term_freq[t] = term_freq.get(t, 0) + 1

    ic = {t: -math.log(f / total_diseases) for t, f in term_freq.items()}

    bulk_insert(con, "hpo_term_ic", ({"hpo_id": t, "ic": v} for t, v in ic.items()))
    bulk_insert(
        con,
        "disease_phenotype_closure",
        ({"disease_id": d, "hpo_id": t} for d, closure in closures.items() for t in closure),
    )
    bulk_insert(
        con,
        "disease_phenotype_weight",
        (
            {
                "disease_id": d,
                "disease_name": names.get(d),
                "total_ic": sum(ic.get(t, 0.0) for t in closure),
                "n_terms": len(closure),
            }
            for d, closure in closures.items()
        ),
    )


LOADERS = {
    "hgnc": load_hgnc,
    "mondo": load_mondo,
    "orphanet": load_orphanet,
    "reactome": load_reactome,
    "dgidb": load_dgidb,
    "hpo": load_hpo,
}


def build(only: list[str] | None = None) -> dict[str, int]:
    paths().ensure()
    results: dict[str, int] = {}
    with session() as con:
        for name, loader in LOADERS.items():
            if only and name not in only:
                continue
            console.print(f"  [cyan]ETL[/cyan] {name} ...")
            results[name] = loader(con)
            console.print(f"    [green]{results[name]:,} righe[/green]")
        console.print("  [cyan]indici[/cyan] ...")
        create_indexes(con)
        counts = table_counts(con)
    for table, n in counts.items():
        console.print(f"    [dim]{table}: {n:,}[/dim]")
    return results
