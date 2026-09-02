"""Stadio 3: dai geni raggiunti ai farmaci gia' approvati che vi agiscono.

Il vincolo "farmaco gia' approvato" e' un filtro hard, non una penalita': un
farmaco sperimentale non e' un candidato al riposizionamento, e' un candidato
allo sviluppo, che e' un altro problema.

Le righe di DGIdb sono una per (farmaco, gene, database a monte): qui vengono
aggregate per coppia farmaco-gene, conservando l'elenco dei database a monte
perche' il numero di fonti indipendenti che concordano e' esso stesso evidenza,
e perche' la provenienza a monte deve restare visibile nel report.
"""

from __future__ import annotations

from collections.abc import Sequence

import duckdb

from ..models import DrugInteraction
from ..provenance import provenance_for


def find_drugs(
    con: duckdb.DuckDBPyConnection,
    target_genes: Sequence[str],
    require_approved: bool = True,
) -> list[DrugInteraction]:
    if not target_genes:
        return []

    placeholders = ", ".join(["?"] * len(target_genes))
    approved_clause = "AND approved" if require_approved else ""

    rows = con.execute(
        f"""
        SELECT
            gene_symbol,
            drug_name,
            any_value(drug_concept_id)                                    AS drug_concept_id,
            list(DISTINCT interaction_type) FILTER (interaction_type IS NOT NULL) AS types,
            list(DISTINCT source_db)        FILTER (source_db IS NOT NULL)        AS dbs,
            max(interaction_score)                                        AS max_score,
            bool_or(approved)                                             AS approved
        FROM dgidb_interactions
        WHERE gene_symbol IN ({placeholders}) {approved_clause}
        GROUP BY gene_symbol, drug_name
        -- Ordinamento esplicito: senza di esso DuckDB non garantisce un ordine
        -- stabile fra esecuzioni, e i candidati a pari punteggio finirebbero
        -- in posizioni diverse a ogni run. Vedi la nota in bundle.build_bundle.
        ORDER BY gene_symbol, drug_name
        """,
        list(target_genes),
    ).fetchall()

    out: list[DrugInteraction] = []
    for gene, drug, concept_id, types, dbs, max_score, approved in rows:
        out.append(
            DrugInteraction(
                drug_name=drug,
                drug_concept_id=concept_id,
                gene_symbol=gene,
                interaction_types=sorted(types or []),
                source_dbs=sorted(dbs or []),
                approved=bool(approved),
                max_interaction_score=float(max_score) if max_score is not None else None,
                provenance=provenance_for(
                    "dgidb", "dgidb_interactions", record_id=f"{gene}/{drug}"
                ),
            )
        )
    return out


def random_control_phenotype_source(con: duckdb.DuckDBPyConnection, seed: int = 0) -> list[str]:
    """Codici Orphanet di una malattia casuale, per il controllo del ramo fenotipico.

    Serve perche' il ponte fenotipico non parte dal gene ma dal profilo clinico
    della malattia interrogata. Sostituire solo il gene causale lascerebbe al
    controllo il profilo fenotipico VERO, e quindi vicini di casa reali: il ramo
    fenotipico continuerebbe a lavorare su dati autentici mentre si pretende di
    misurare cosa succede con dati falsi.

    Si estrae fra le malattie che hanno annotazioni fenotipiche, altrimenti il
    controllo non produrrebbe alcun ponte e sembrerebbe superato per merito
    quando invece non e' stato nemmeno eseguito.
    """
    row = con.execute(
        """
        SELECT disease_id
        FROM disease_phenotype_weight
        WHERE disease_id LIKE 'ORPHA:%' AND n_terms >= 20
        ORDER BY hash(disease_id || ?)
        LIMIT 1
        """,
        [str(seed)],
    ).fetchone()
    return [row[0]] if row else []


def random_control_gene(con: duckdb.DuckDBPyConnection, seed: int = 0) -> str:
    """Gene casuale fra quelli annotati in Reactome, per il controllo negativo.

    Usato da `--shuffle-control`: si sostituisce il gene causale con uno estratto
    a caso e si lascia identico tutto il resto. Se il ranking risultante e'
    indistinguibile da quello reale, lo score non sta misurando nulla.
    """
    row = con.execute(
        """
        SELECT g.symbol
        FROM genes g
        WHERE g.entrez_id IN (SELECT DISTINCT entrez_id FROM reactome_gene_pathway)
        ORDER BY hash(g.symbol || ?)
        LIMIT 1
        """,
        [str(seed)],
    ).fetchone()
    return row[0] if row else "TP53"
