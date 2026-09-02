"""Store locale su DuckDB.

Perche' DuckDB: embedded, colonnare, zero configurazione e zero servizi. Il
vincolo "100% locale" e' credibile solo se installare il progetto significa
`uv sync` e nient'altro; un Neo4j o un Postgres da avviare lo tradirebbe.

La traversata dei pathway avviene su un grafo NetworkX costruito da queste
tabelle (vedi pipeline/pathways.py): SQL per filtrare e aggregare, grafo in
memoria per i cammini.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb

from .config import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS genes (
    symbol         VARCHAR PRIMARY KEY,
    hgnc_id        VARCHAR,
    entrez_id      BIGINT,
    uniprot_ids    VARCHAR,
    name           VARCHAR,
    prev_symbols   VARCHAR,
    alias_symbols  VARCHAR
);

CREATE TABLE IF NOT EXISTS diseases (
    mondo_id    VARCHAR PRIMARY KEY,
    name        VARCHAR,
    definition  VARCHAR
);

CREATE TABLE IF NOT EXISTS disease_synonyms (
    mondo_id  VARCHAR,
    synonym   VARCHAR
);

CREATE TABLE IF NOT EXISTS disease_xrefs (
    mondo_id  VARCHAR,
    xref      VARCHAR
);

CREATE TABLE IF NOT EXISTS disease_is_a (
    child_id   VARCHAR,
    parent_id  VARCHAR
);

CREATE TABLE IF NOT EXISTS orphanet_gene_assoc (
    orpha_code          VARCHAR,
    disorder_name       VARCHAR,
    gene_symbol         VARCHAR,
    gene_name           VARCHAR,
    hgnc_id             VARCHAR,
    omim_id             VARCHAR,
    association_type    VARCHAR,
    association_status  VARCHAR,
    is_causal           BOOLEAN,
    pmids               VARCHAR
);

CREATE TABLE IF NOT EXISTS reactome_gene_pathway (
    entrez_id      BIGINT,
    pathway_id     VARCHAR,
    pathway_name   VARCHAR,
    evidence_code  VARCHAR
);

CREATE TABLE IF NOT EXISTS reactome_relations (
    parent_id  VARCHAR,
    child_id   VARCHAR
);

CREATE TABLE IF NOT EXISTS reactome_pathways (
    pathway_id    VARCHAR PRIMARY KEY,
    pathway_name  VARCHAR
);

CREATE TABLE IF NOT EXISTS hpo_terms (
    hpo_id  VARCHAR PRIMARY KEY,
    name    VARCHAR
);

CREATE TABLE IF NOT EXISTS hpo_is_a (
    child_id   VARCHAR,
    parent_id  VARCHAR
);

CREATE TABLE IF NOT EXISTS disease_phenotypes (
    disease_id    VARCHAR,
    disease_name  VARCHAR,
    hpo_id        VARCHAR,
    evidence      VARCHAR,
    frequency     VARCHAR
);

-- Derivate, calcolate a build time (vedi sources/build.py::load_hpo).
-- Precalcolarle sposta il costo dalla query alla costruzione dello store:
-- la chiusura per transitivita' delle annotazioni si calcola una volta,
-- non a ogni interrogazione.
CREATE TABLE IF NOT EXISTS hpo_term_ic (
    hpo_id  VARCHAR PRIMARY KEY,
    ic      DOUBLE
);

CREATE TABLE IF NOT EXISTS disease_phenotype_closure (
    disease_id  VARCHAR,
    hpo_id      VARCHAR
);

CREATE TABLE IF NOT EXISTS disease_phenotype_weight (
    disease_id    VARCHAR PRIMARY KEY,
    disease_name  VARCHAR,
    total_ic      DOUBLE,
    n_terms       BIGINT
);

CREATE TABLE IF NOT EXISTS dgidb_interactions (
    gene_symbol        VARCHAR,
    gene_concept_id    VARCHAR,
    drug_name          VARCHAR,
    drug_concept_id    VARCHAR,
    interaction_type   VARCHAR,
    interaction_score  DOUBLE,
    source_db          VARCHAR,
    approved           BOOLEAN
);
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_genes_entrez ON genes(entrez_id)",
    "CREATE INDEX IF NOT EXISTS idx_xrefs_xref ON disease_xrefs(xref)",
    "CREATE INDEX IF NOT EXISTS idx_syn_mondo ON disease_synonyms(mondo_id)",
    "CREATE INDEX IF NOT EXISTS idx_isa_parent ON disease_is_a(parent_id)",
    "CREATE INDEX IF NOT EXISTS idx_orpha_code ON orphanet_gene_assoc(orpha_code)",
    "CREATE INDEX IF NOT EXISTS idx_rgp_entrez ON reactome_gene_pathway(entrez_id)",
    "CREATE INDEX IF NOT EXISTS idx_rgp_pathway ON reactome_gene_pathway(pathway_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_parent ON reactome_relations(parent_id)",
    "CREATE INDEX IF NOT EXISTS idx_rel_child ON reactome_relations(child_id)",
    "CREATE INDEX IF NOT EXISTS idx_dgidb_gene ON dgidb_interactions(gene_symbol)",
    "CREATE INDEX IF NOT EXISTS idx_hpo_isa_child ON hpo_is_a(child_id)",
    "CREATE INDEX IF NOT EXISTS idx_dp_disease ON disease_phenotypes(disease_id)",
    "CREATE INDEX IF NOT EXISTS idx_dp_hpo ON disease_phenotypes(hpo_id)",
    "CREATE INDEX IF NOT EXISTS idx_dpc_hpo ON disease_phenotype_closure(hpo_id)",
    "CREATE INDEX IF NOT EXISTS idx_dpc_disease ON disease_phenotype_closure(disease_id)",
]

# Colonne attese per ogni tabella, con il tipo DuckDB: (nome, tipo).
# Il tipo serve al caricamento via staging, che legge tutto come VARCHAR e
# poi effettua il cast esplicito.
SCHEMA_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "genes": [
        ("symbol", "VARCHAR"),
        ("hgnc_id", "VARCHAR"),
        ("entrez_id", "BIGINT"),
        ("uniprot_ids", "VARCHAR"),
        ("name", "VARCHAR"),
        ("prev_symbols", "VARCHAR"),
        ("alias_symbols", "VARCHAR"),
    ],
    "diseases": [("mondo_id", "VARCHAR"), ("name", "VARCHAR"), ("definition", "VARCHAR")],
    "disease_synonyms": [("mondo_id", "VARCHAR"), ("synonym", "VARCHAR")],
    "disease_xrefs": [("mondo_id", "VARCHAR"), ("xref", "VARCHAR")],
    "disease_is_a": [("child_id", "VARCHAR"), ("parent_id", "VARCHAR")],
    "orphanet_gene_assoc": [
        ("orpha_code", "VARCHAR"),
        ("disorder_name", "VARCHAR"),
        ("gene_symbol", "VARCHAR"),
        ("gene_name", "VARCHAR"),
        ("hgnc_id", "VARCHAR"),
        ("omim_id", "VARCHAR"),
        ("association_type", "VARCHAR"),
        ("association_status", "VARCHAR"),
        ("is_causal", "BOOLEAN"),
        ("pmids", "VARCHAR"),
    ],
    "reactome_gene_pathway": [
        ("entrez_id", "BIGINT"),
        ("pathway_id", "VARCHAR"),
        ("pathway_name", "VARCHAR"),
        ("evidence_code", "VARCHAR"),
    ],
    "reactome_relations": [("parent_id", "VARCHAR"), ("child_id", "VARCHAR")],
    "reactome_pathways": [("pathway_id", "VARCHAR"), ("pathway_name", "VARCHAR")],
    "hpo_terms": [("hpo_id", "VARCHAR"), ("name", "VARCHAR")],
    "hpo_is_a": [("child_id", "VARCHAR"), ("parent_id", "VARCHAR")],
    "disease_phenotypes": [
        ("disease_id", "VARCHAR"),
        ("disease_name", "VARCHAR"),
        ("hpo_id", "VARCHAR"),
        ("evidence", "VARCHAR"),
        ("frequency", "VARCHAR"),
    ],
    "hpo_term_ic": [("hpo_id", "VARCHAR"), ("ic", "DOUBLE")],
    "disease_phenotype_closure": [("disease_id", "VARCHAR"), ("hpo_id", "VARCHAR")],
    "disease_phenotype_weight": [
        ("disease_id", "VARCHAR"),
        ("disease_name", "VARCHAR"),
        ("total_ic", "DOUBLE"),
        ("n_terms", "BIGINT"),
    ],
    "dgidb_interactions": [
        ("gene_symbol", "VARCHAR"),
        ("gene_concept_id", "VARCHAR"),
        ("drug_name", "VARCHAR"),
        ("drug_concept_id", "VARCHAR"),
        ("interaction_type", "VARCHAR"),
        ("interaction_score", "DOUBLE"),
        ("source_db", "VARCHAR"),
        ("approved", "BOOLEAN"),
    ],
}

COLUMNS: dict[str, list[str]] = {t: [c for c, _ in cols] for t, cols in SCHEMA_COLUMNS.items()}


def connect(db_path: Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = db_path or paths().db
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA)
    return con


@contextmanager
def session(
    db_path: Path | None = None, read_only: bool = False
) -> Iterator[duckdb.DuckDBPyConnection]:
    con = connect(db_path, read_only=read_only)
    try:
        yield con
    finally:
        con.close()


def create_indexes(con: duckdb.DuckDBPyConnection) -> None:
    for stmt in INDEXES:
        con.execute(stmt)


def bulk_insert(
    con: duckdb.DuckDBPyConnection,
    table: str,
    rows: Iterable[dict[str, Any]],
    batch_size: int = 0,  # accettato per compatibilita', non usato
) -> int:
    """Inserimento massivo via staging su TSV temporaneo.

    PERCHE' NON executemany
    `DuckDBPyConnection.executemany` inserisce riga per riga a circa 150 righe
    al secondo: sulle centinaia di migliaia di righe di Mondo e Orphanet
    significa ore. Scrivere un TSV temporaneo e darlo in pasto al lettore CSV
    nativo sposta il lavoro nel motore C++ ed e' tre ordini di grandezza piu'
    veloce, senza aggiungere dipendenze come pandas o pyarrow.

    Lo streaming resta: le righe passano dall'iteratore al file una alla volta,
    quindi la memoria non cresce con la dimensione dell'input.
    """
    cols = SCHEMA_COLUMNS[table]
    names = [c for c, _ in cols]

    staging = paths().processed / f".staging_{table}.tsv"
    staging.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    with staging.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        for row in rows:
            writer.writerow(["" if (v := row.get(c)) is None else v for c in names])
            total += 1

    if total == 0:
        staging.unlink(missing_ok=True)
        return 0

    read_columns = ", ".join(f"'{c}':'VARCHAR'" for c in names)
    select_exprs = ", ".join(
        f"nullif({c}, '')" if typ == "VARCHAR" else f"try_cast(nullif({c}, '') AS {typ})"
        for c, typ in cols
    )
    con.execute(
        f"""
        INSERT INTO {table} ({", ".join(names)})
        SELECT {select_exprs}
        FROM read_csv('{staging.resolve().as_posix()}', delim='\t', header=false,
                      all_varchar=true, ignore_errors=true, columns={{{read_columns}}})
        """
    )
    staging.unlink(missing_ok=True)
    return total


def truncate(con: duckdb.DuckDBPyConnection, *tables: str) -> None:
    for t in tables:
        con.execute(f"DELETE FROM {t}")


def table_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    out = {}
    for table in COLUMNS:
        try:
            out[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        except duckdb.Error:
            out[table] = 0
    return out


def is_built(con: duckdb.DuckDBPyConnection) -> bool:
    """Vero se le tabelle essenziali sono popolate."""
    counts = table_counts(con)
    essential = [
        "genes",
        "diseases",
        "orphanet_gene_assoc",
        "reactome_gene_pathway",
        "dgidb_interactions",
    ]
    return all(counts.get(t, 0) > 0 for t in essential)
