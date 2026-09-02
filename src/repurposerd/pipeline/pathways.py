"""Stadio 2: dal gene causale ai geni funzionalmente vicini, via Reactome.

Tre distanze, e la distanza conta:
  hop 0 — il bersaglio del farmaco e' il gene causale stesso
  hop 1 — il bersaglio condivide un pathway con il gene causale
  hop 2 — il bersaglio sta in un pathway padre o figlio di quelli del gene causale

IL FILTRO CHE CONTA PIU' DI TUTTI
Reactome annota i geni a ogni livello della gerarchia: TSC2 appartiene sia a
"mTORC1-mediated signalling" (una manciata di geni) sia a "Signal Transduction"
(migliaia). Senza un tetto alla dimensione del pathway, qualunque gene risulta
"nello stesso pathway" di qualunque altro e l'intero metodo collassa in un
generatore di coincidenze. `max_pathway_size` e' cio' che tiene in piedi il resto.
"""

from __future__ import annotations

from collections.abc import Sequence

import duckdb
import networkx as nx

from ..models import CausalGene, Pathway, PathwayLink
from ..provenance import provenance_for

# CTE riusata: la dimensione di un pathway e' il numero di geni umani distinti
# che vi sono annotati.
_SIZES_CTE = """
WITH pathway_sizes AS (
    SELECT pathway_id, count(DISTINCT entrez_id) AS size
    FROM reactome_gene_pathway
    GROUP BY pathway_id
)
"""


def pathway_hierarchy(con: duckdb.DuckDBPyConnection) -> nx.DiGraph:
    """Gerarchia dei pathway umani come grafo diretto padre -> figlio."""
    g = nx.DiGraph()
    for parent, child in con.execute(
        "SELECT parent_id, child_id FROM reactome_relations"
    ).fetchall():
        g.add_edge(parent, child)
    return g


def pathways_of_gene(
    con: duckdb.DuckDBPyConnection, entrez_id: int, max_size: int
) -> list[tuple[str, str, int]]:
    """Pathway che contengono il gene, gia' filtrati per specificita'.

    Ritorna (pathway_id, pathway_name, size), dal piu' specifico al meno.
    """
    return con.execute(
        _SIZES_CTE
        + """
        SELECT DISTINCT rgp.pathway_id, rgp.pathway_name, ps.size
        FROM reactome_gene_pathway rgp
        JOIN pathway_sizes ps USING (pathway_id)
        WHERE rgp.entrez_id = ? AND ps.size <= ?
        ORDER BY ps.size ASC
        """,
        [entrez_id, max_size],
    ).fetchall()


def genes_in_pathways(
    con: duckdb.DuckDBPyConnection, pathway_ids: Sequence[str]
) -> list[tuple[str, str]]:
    """(gene_symbol, pathway_id) per i pathway dati. Solo geni con simbolo HGNC noto."""
    if not pathway_ids:
        return []
    placeholders = ", ".join(["?"] * len(pathway_ids))
    return con.execute(
        f"""
        SELECT DISTINCT g.symbol, rgp.pathway_id
        FROM reactome_gene_pathway rgp
        JOIN genes g ON g.entrez_id = rgp.entrez_id
        WHERE rgp.pathway_id IN ({placeholders})
        """,
        list(pathway_ids),
    ).fetchall()


def _pathway_model(con: duckdb.DuckDBPyConnection, pid: str, name: str, size: int) -> Pathway:
    return Pathway(
        reactome_id=pid,
        name=name,
        size=size,
        provenance=provenance_for("reactome", "reactome_gene_to_pathway", record_id=pid),
    )


def expand(
    con: duckdb.DuckDBPyConnection,
    causal_genes: list[CausalGene],
    max_pathway_size: int = 200,
    max_hops: int = 2,
) -> dict[str, PathwayLink]:
    """Espande dai geni causali all'insieme dei geni raggiungibili.

    Ritorna una mappa gene_bersaglio -> miglior collegamento, dove "migliore"
    significa: minor numero di hop e, a parita' di hop, il pathway piu' piccolo,
    cioe' quello che porta piu' informazione.
    """
    hierarchy = pathway_hierarchy(con)
    best: dict[str, PathwayLink] = {}
    # Tutti i pathway che collegano ciascun bersaglio, non solo quello vincente:
    # il piu' piccolo massimizza la specificita' statistica ma non e' sempre il
    # piu' significativo da leggere, e il revisore deve poter vedere gli altri.
    all_shared: dict[str, set[tuple[int, str]]] = {}

    def offer(link: PathwayLink) -> None:
        all_shared.setdefault(link.target_gene, set()).add((link.pathway.size, link.pathway.name))
        cur = best.get(link.target_gene)
        if cur is None or (link.hops, link.pathway.size) < (cur.hops, cur.pathway.size):
            best[link.target_gene] = link

    for cg in causal_genes:
        symbol = cg.gene.symbol
        if cg.gene.entrez_id is None:
            continue  # senza Entrez ID non e' agganciabile a Reactome

        direct = pathways_of_gene(con, cg.gene.entrez_id, max_pathway_size)
        if not direct:
            continue

        pathway_meta = {pid: (name, size) for pid, name, size in direct}

        # --- hop 0: il gene causale stesso, ancorato al suo pathway piu' specifico
        pid0, name0, size0 = direct[0]
        offer(
            PathwayLink(
                causal_gene=symbol,
                target_gene=symbol,
                pathway=_pathway_model(con, pid0, name0, size0),
                hops=0,
                route=f"{symbol} e' il gene causale stesso; pathway piu' specifico: {name0}",
            )
        )

        # --- hop 1: geni che condividono un pathway con il gene causale
        if max_hops >= 1:
            for target, pid in genes_in_pathways(con, list(pathway_meta)):
                if target == symbol:
                    continue
                name, size = pathway_meta[pid]
                offer(
                    PathwayLink(
                        causal_gene=symbol,
                        target_gene=target,
                        pathway=_pathway_model(con, pid, name, size),
                        hops=1,
                        route=f"{symbol} e {target} sono entrambi annotati in «{name}»",
                    )
                )

        # --- hop 2: pathway padre o figlio, ancora entro il tetto di dimensione
        if max_hops >= 2:
            neighbour_ids: set[str] = set()
            for pid in pathway_meta:
                if pid not in hierarchy:
                    continue
                neighbour_ids.update(hierarchy.successors(pid))
                neighbour_ids.update(hierarchy.predecessors(pid))
            neighbour_ids -= set(pathway_meta)
            if not neighbour_ids:
                continue

            placeholders = ", ".join(["?"] * len(neighbour_ids))
            neighbour_rows = con.execute(
                _SIZES_CTE
                + f"""
                SELECT p.pathway_id, p.pathway_name, ps.size
                FROM reactome_pathways p
                JOIN pathway_sizes ps USING (pathway_id)
                WHERE p.pathway_id IN ({placeholders}) AND ps.size <= ?
                """,
                [*neighbour_ids, max_pathway_size],
            ).fetchall()
            neighbour_meta = {pid: (name, size) for pid, name, size in neighbour_rows}

            for target, pid in genes_in_pathways(con, list(neighbour_meta)):
                if target == symbol:
                    continue
                name, size = neighbour_meta[pid]
                offer(
                    PathwayLink(
                        causal_gene=symbol,
                        target_gene=target,
                        pathway=_pathway_model(con, pid, name, size),
                        hops=2,
                        route=(
                            f"{target} appartiene a «{name}», pathway adiacente nella "
                            f"gerarchia Reactome a quelli che contengono {symbol}"
                        ),
                    )
                )

    for target, link in best.items():
        link.shared_pathways = [name for _size, name in sorted(all_shared.get(target, set()))]

    return best
