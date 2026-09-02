"""Stadio 1: dalla stringa in input alla malattia canonica e ai suoi geni causali.

Due passaggi distinti, deliberatamente separati:
  - normalizzazione dell'identita' della malattia (Mondo)
  - attribuzione del gene causale (Orphanet, associazioni curate)

Tenerli separati significa che un errore di risoluzione del nome non si
travestera' mai da errore di biologia nel report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import duckdb

from ..models import CausalGene, Disease, Gene
from ..provenance import provenance_for

MONDO_RE = re.compile(r"^MONDO:\d{7}$", re.IGNORECASE)
ORPHA_RE = re.compile(r"^(?:ORPHA|ORPHANET):(\d+)$", re.IGNORECASE)
OMIM_RE = re.compile(r"^(?:OMIM|MIM):(\d+)$", re.IGNORECASE)


class DiseaseNotFound(LookupError):
    pass


class AmbiguousDisease(LookupError):
    def __init__(self, query: str, matches: list[tuple[str, str]]) -> None:
        self.matches = matches
        listing = "\n".join(f"  {mid}  {name}" for mid, name in matches[:10])
        super().__init__(
            f"'{query}' corrisponde a piu' malattie. "
            f"Ripeti con un identificatore preciso:\n{listing}"
        )


@dataclass
class ResolvedDisease:
    disease: Disease
    causal_genes: list[CausalGene]


def _normalize_orpha(xref: str) -> str | None:
    m = ORPHA_RE.match(xref.strip())
    return f"ORPHA:{m.group(1)}" if m else None


def _load_disease(con: duckdb.DuckDBPyConnection, mondo_id: str) -> Disease:
    row = con.execute(
        "SELECT mondo_id, name FROM diseases WHERE upper(mondo_id) = upper(?)", [mondo_id]
    ).fetchone()
    if not row:
        raise DiseaseNotFound(f"{mondo_id} non presente nel subset Mondo caricato.")

    synonyms = [
        r[0]
        for r in con.execute(
            "SELECT synonym FROM disease_synonyms WHERE mondo_id = ?", [row[0]]
        ).fetchall()
    ]
    xrefs = [
        r[0]
        for r in con.execute(
            "SELECT xref FROM disease_xrefs WHERE mondo_id = ?", [row[0]]
        ).fetchall()
    ]

    orpha = sorted({o for x in xrefs if (o := _normalize_orpha(x))})
    omim = sorted({f"OMIM:{m.group(1)}" for x in xrefs if (m := OMIM_RE.match(x.strip()))})

    return Disease(
        mondo_id=row[0],
        label=row[1],
        synonyms=synonyms,
        orpha_codes=orpha,
        omim_ids=omim,
        provenance=provenance_for("mondo", "mondo_rare_obo", record_id=row[0]),
    )


def _mondo_from_xref(con: duckdb.DuckDBPyConnection, query: str) -> str | None:
    """Risale a un Mondo ID partendo da un identificatore Orphanet o OMIM."""
    m = ORPHA_RE.match(query)
    if m:
        code = m.group(1)
        row = con.execute(
            "SELECT mondo_id FROM disease_xrefs WHERE upper(xref) IN (?, ?) LIMIT 1",
            [f"ORPHANET:{code}", f"ORPHA:{code}"],
        ).fetchone()
        return row[0] if row else None

    m = OMIM_RE.match(query)
    if m:
        row = con.execute(
            "SELECT mondo_id FROM disease_xrefs WHERE upper(xref) = ? LIMIT 1",
            [f"OMIM:{m.group(1)}"],
        ).fetchone()
        return row[0] if row else None
    return None


def _mondo_from_text(con: duckdb.DuckDBPyConnection, query: str) -> str:
    """Ricerca testuale: nome esatto, poi sinonimo esatto, poi sottostringa.

    L'ambiguita' viene sollevata come errore invece di essere risolta a caso:
    scegliere silenziosamente una fra dieci malattie simili e' il modo piu'
    rapido per produrre un report perfettamente formattato e completamente sbagliato.
    """
    q = query.strip().lower()

    exact = con.execute("SELECT mondo_id, name FROM diseases WHERE lower(name) = ?", [q]).fetchall()
    if len(exact) == 1:
        return exact[0][0]
    if len(exact) > 1:
        raise AmbiguousDisease(query, exact)

    syn = con.execute(
        "SELECT DISTINCT d.mondo_id, d.name FROM disease_synonyms s "
        "JOIN diseases d USING (mondo_id) WHERE lower(s.synonym) = ?",
        [q],
    ).fetchall()
    if len(syn) == 1:
        return syn[0][0]
    if len(syn) > 1:
        raise AmbiguousDisease(query, syn)

    like = con.execute(
        "SELECT mondo_id, name FROM diseases WHERE lower(name) LIKE ? "
        "ORDER BY length(name) LIMIT 25",
        [f"%{q}%"],
    ).fetchall()
    if len(like) == 1:
        return like[0][0]
    if len(like) > 1:
        raise AmbiguousDisease(query, like)

    raise DiseaseNotFound(
        f"Nessuna malattia corrisponde a '{query}'. "
        "Nota: e' caricato il subset 'rare' di Mondo, che copre solo le malattie rare."
    )


def resolve_disease(con: duckdb.DuckDBPyConnection, query: str) -> Disease:
    query = query.strip()
    if MONDO_RE.match(query):
        return _load_disease(con, query.upper())
    if mondo_id := _mondo_from_xref(con, query):
        return _load_disease(con, mondo_id)
    return _load_disease(con, _mondo_from_text(con, query))


def _descendant_orpha_codes(
    con: duckdb.DuckDBPyConnection, mondo_id: str, max_depth: int = 3
) -> list[str]:
    """Codici Orphanet dei sottotipi di una malattia, scendendo nella gerarchia Mondo.

    Serve perche' Orphanet colloca spesso l'associazione con il gene sui
    sottotipi clinici e non sul termine padre. Niemann-Pick tipo C ne e' il caso
    tipico: ORPHA:646 non porta alcun gene, mentre le sue cinque forme cliniche
    riportano tutte NPC1 e NPC2. Senza questa discesa il tool fallirebbe proprio
    sulle malattie descritte in modo piu' accurato.
    """
    frontier = {mondo_id}
    seen = {mondo_id}
    for _ in range(max_depth):
        if not frontier:
            break
        placeholders = ", ".join(["?"] * len(frontier))
        children = {
            r[0]
            for r in con.execute(
                f"SELECT child_id FROM disease_is_a WHERE parent_id IN ({placeholders})",
                list(frontier),
            ).fetchall()
        }
        frontier = children - seen
        seen |= children

    descendants = seen - {mondo_id}
    if not descendants:
        return []

    placeholders = ", ".join(["?"] * len(descendants))
    rows = con.execute(
        f"SELECT DISTINCT xref FROM disease_xrefs WHERE mondo_id IN ({placeholders})",
        list(descendants),
    ).fetchall()
    return sorted({o for (x,) in rows if (o := _normalize_orpha(x))})


def _query_causal(con: duckdb.DuckDBPyConnection, orpha_codes: list[str]) -> list[tuple]:
    if not orpha_codes:
        return []
    placeholders = ", ".join(["?"] * len(orpha_codes))
    return con.execute(
        f"""
        SELECT o.gene_symbol, o.gene_name, o.association_type, o.pmids,
               g.hgnc_id, g.entrez_id, g.uniprot_ids, o.orpha_code
        FROM orphanet_gene_assoc o
        LEFT JOIN genes g ON g.symbol = o.gene_symbol
        WHERE o.orpha_code IN ({placeholders}) AND o.is_causal
        ORDER BY o.gene_symbol
        """,
        orpha_codes,
    ).fetchall()


def causal_genes_for(con: duckdb.DuckDBPyConnection, disease: Disease) -> list[CausalGene]:
    """Geni causali via le associazioni curate di Orphanet.

    Si accettano solo i tipi di associazione elencati in
    parsers.CAUSAL_ASSOCIATION_TYPES: geni modificatori o di suscettibilita'
    descrivono un rapporto reale ma non monogenico causale, e ammetterli qui
    propagherebbe rumore in tutti gli stadi successivi. Per la sclerosi tuberosa
    questo filtro e' cio' che tiene fuori IFNG, annotato da Orphanet come
    modificatore e non come causa.

    Se il termine non porta geni propri, si scende ai sottotipi (vedi
    `_descendant_orpha_codes`).
    """
    rows = _query_causal(con, disease.orpha_codes)
    if not rows:
        rows = _query_causal(con, _descendant_orpha_codes(con, disease.mondo_id))

    out: list[CausalGene] = []
    seen: set[str] = set()
    for symbol, gene_name, assoc_type, pmids, hgnc_id, entrez_id, uniprot, orpha in rows:
        if symbol in seen:
            continue
        seen.add(symbol)
        out.append(
            CausalGene(
                gene=Gene(
                    symbol=symbol,
                    hgnc_id=hgnc_id,
                    entrez_id=entrez_id,
                    uniprot_ids=[u for u in (uniprot or "").split("|") if u],
                    name=gene_name,
                ),
                association_type=assoc_type,
                validation_pmids=[p for p in (pmids or "").split(",") if p],
                provenance=provenance_for(
                    "orphanet", "orphanet_gene_associations", record_id=f"{orpha}/{symbol}"
                ),
            )
        )
    return out


def resolve(con: duckdb.DuckDBPyConnection, query: str) -> ResolvedDisease:
    disease = resolve_disease(con, query)
    return ResolvedDisease(disease=disease, causal_genes=causal_genes_for(con, disease))
