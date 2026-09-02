"""Seconda strategia di ricerca: il ponte fenotipico.

PERCHE' ESISTE
Il ramo basato sui pathway cattura i casi in cui il farmaco agisce sullo stesso
processo alterato dalla malattia. Non cattura quelli in cui agisce su una
conseguenza a valle di quel processo, e non e' una questione di taratura: se le
due proteine non compaiono insieme in nessun pathway Reactome, nessuna soglia
le avvicina.

Il caso pilota Niemann-Pick tipo C lo ha mostrato in modo netto (vedi
docs/PILOT_RESULTS.md): miglustat inibisce UGCG, ma NPC1 e UGCG non condividono
alcun pathway, a nessuna dimensione. Il collegamento reale passa per la
fisiopatologia — il difetto di trasporto del colesterolo provoca un accumulo
secondario di sfingolipidi — e la fisiopatologia si manifesta come **fenotipo**.

L'IDEA
Due malattie che si somigliano clinicamente condividono spesso la biologia a
valle, anche quando i loro geni causali stanno in rami separati dell'ontologia
dei pathway. Se la malattia interrogata somiglia a un'altra malattia rara, i
geni causali di quest'ultima diventano un secondo punto di ingresso per la
stessa espansione sui pathway gia' usata dal ramo principale.

    NPC --fenotipo--> Gaucher --gene--> GBA1 --pathway--> UGCG --farmaco--> miglustat

COME SI MISURA LA SOMIGLIANZA
Jaccard pesato per contenuto informativo, sulla chiusura per transitivita' delle
annotazioni HPO (entrambe precalcolate a build time, vedi sources/build.py):

    sim(A, B) = IC(intersezione delle chiusure) / IC(unione delle chiusure)

Il peso per IC serve a non far somigliare due malattie perche' condividono
banalita': "anomalia del sistema nervoso" e' annotata su meta' delle malattie
rare e non distingue nulla, mentre un termine raro identifica una manciata di
casi. La chiusura per transitivita' serve a rendere confrontabili annotazioni
curate a livelli di dettaglio diversi.

COSA QUESTO METODO NON DIMOSTRA
Che due malattie si somiglino clinicamente non implica che condividano un
meccanismo: epatosplenomegalia e atassia accomunano molte malattie da accumulo
lisosomiale per ragioni diverse fra loro. Il ponte fenotipico e' un modo di
generare ipotesi che il ramo pathway non puo' vedere, non una prova di
parentela meccanicistica. Per questo i candidati che arrivano da qui portano
nel report la loro provenienza e una penalita' esplicita nel punteggio.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from ..models import Provenance
from ..provenance import provenance_for


@dataclass
class SharedPhenotype:
    hpo_id: str
    name: str
    ic: float


@dataclass
class DiseaseMatch:
    """Una malattia fenotipicamente simile a quella interrogata."""

    disease_id: str  # ORPHA:... oppure OMIM:...
    disease_name: str | None
    similarity: float  # Jaccard pesato per IC, in [0, 1]
    shared_count: int
    shared_phenotypes: list[SharedPhenotype] = field(default_factory=list)
    orpha_codes: list[str] = field(default_factory=list)
    provenance: Provenance | None = None

    def describe(self) -> str:
        top = ", ".join(p.name for p in self.shared_phenotypes[:4])
        return f"{self.disease_name or self.disease_id} (somiglianza {self.similarity:.2f}): {top}"


def annotation_ids_for(con: duckdb.DuckDBPyConnection, orpha_codes: list[str]) -> list[str]:
    """Identificatori usati da phenotype.hpoa per questa malattia.

    HPO annota con codici ORPHA e OMIM; la pipeline lavora su Mondo. Si passa
    per i codici Orphanet della malattia, che sono gia' stati risolti a monte.
    """
    if not orpha_codes:
        return []
    placeholders = ", ".join(["?"] * len(orpha_codes))
    rows = con.execute(
        f"SELECT DISTINCT disease_id FROM disease_phenotype_weight "
        f"WHERE disease_id IN ({placeholders})",
        orpha_codes,
    ).fetchall()
    return [r[0] for r in rows]


def _orpha_codes_for_annotation(con: duckdb.DuckDBPyConnection, disease_id: str) -> list[str]:
    """Dall'identificatore usato da HPO ai codici Orphanet, da cui si ricavano i geni.

    Un ORPHA: e' gia' quello che serve. Un OMIM: va ricondotto passando per il
    termine Mondo che lo referenzia, perche' la fonte dei geni causali di questo
    progetto e' Orphanet e non OMIM (i cui dati grezzi sono esclusi per licenza).
    """
    if disease_id.startswith("ORPHA:"):
        return [disease_id]
    if not disease_id.startswith("OMIM:"):
        return []

    rows = con.execute(
        """
        SELECT DISTINCT x2.xref
        FROM disease_xrefs x1
        JOIN disease_xrefs x2 USING (mondo_id)
        WHERE upper(x1.xref) = ?
          AND (upper(x2.xref) LIKE 'ORPHANET:%' OR upper(x2.xref) LIKE 'ORPHA:%')
        """,
        [disease_id.upper()],
    ).fetchall()
    out = []
    for (xref,) in rows:
        code = xref.split(":", 1)[1]
        out.append(f"ORPHA:{code}")
    return sorted(set(out))


def self_match_ids(con: duckdb.DuckDBPyConnection, mondo_id: str) -> set[str]:
    """Identificatori HPO che designano la malattia interrogata, non un'altra.

    Senza questa esclusione i primi risultati per Niemann-Pick tipo C sono
    `OMIM:257220` e `OMIM:607625`, cioe' NPC1 e NPC2: la stessa malattia sotto
    un altro identificatore, che si presenta come la sua vicina piu' prossima.
    Si escludono il termine Mondo, i suoi genitori e i suoi figli, perche' i
    sottotipi clinici di una malattia non sono malattie diverse da cui prendere
    a prestito un gene causale: quel gene e' gia' nel ramo principale.
    """
    rows = con.execute(
        """
        WITH seed AS (SELECT ? AS mondo_id),
        fam AS (
            SELECT mondo_id FROM seed
            UNION SELECT child_id  FROM disease_is_a WHERE parent_id IN (SELECT mondo_id FROM seed)
            UNION SELECT parent_id FROM disease_is_a WHERE child_id  IN (SELECT mondo_id FROM seed)
        )
        SELECT DISTINCT upper(replace(xref, 'Orphanet:', 'ORPHA:'))
        FROM disease_xrefs WHERE mondo_id IN (SELECT mondo_id FROM fam)
        """,
        [mondo_id],
    ).fetchall()
    return {r[0] for r in rows if r[0].startswith(("ORPHA:", "OMIM:"))}


def similar_diseases(
    con: duckdb.DuckDBPyConnection,
    orpha_codes: list[str],
    top_k: int = 30,
    min_similarity: float = 0.15,
    min_shared_terms: int = 5,
    max_shared_listed: int = 8,
    exclude_ids: set[str] | None = None,
) -> list[DiseaseMatch]:
    """Malattie fenotipicamente simili, ordinate per somiglianza decrescente.

    `min_shared_terms` esiste perche' il Jaccard pesato puo' produrre valori
    apparentemente alti fra due malattie annotate con pochissimi termini, uno
    dei quali raro. Richiedere una sovrapposizione minima di sostanza evita che
    l'intero ramo si fondi su una singola coincidenza di annotazione.

    PERCHE' `top_k` E' GENEROSO (30, non 10)
    Misurato sul caso pilota: i vicini fenotipici piu' prossimi di Niemann-Pick
    tipo C sono altre malattie neurodegenerative e da accumulo lisosomiale, e la
    malattia di Gaucher — quella che porta il riposizionamento noto — compare
    intorno alla trentacinquesima posizione. Non e' un difetto della metrica: e'
    che NPC somiglia clinicamente a molte malattie, e Gaucher e' una fra queste.

    Restringere a dieci vicini darebbe l'illusione della precisione scartando il
    caso che il ramo esiste per catturare. La scelta e' quindi l'opposta: rete
    ampia, e discriminazione affidata al punteggio finale del candidato, dove la
    somiglianza entra come penalita' esplicita (componente `route_directness`).
    """
    query_ids = annotation_ids_for(con, orpha_codes)
    if not query_ids:
        return []

    excluded = {i.upper() for i in (exclude_ids or set())} | {i.upper() for i in query_ids}
    placeholders = ", ".join(["?"] * len(query_ids))
    rows = con.execute(
        f"""
        WITH q AS (
            SELECT DISTINCT hpo_id
            FROM disease_phenotype_closure
            WHERE disease_id IN ({placeholders})
        ),
        qw AS (
            SELECT sum(i.ic) AS w FROM q JOIN hpo_term_ic i USING (hpo_id)
        )
        SELECT
            c.disease_id,
            any_value(w.disease_name)                    AS disease_name,
            sum(i.ic)                                    AS intersection_ic,
            (SELECT w FROM qw) + any_value(w.total_ic) - sum(i.ic) AS union_ic,
            count(*)                                     AS shared_terms
        FROM disease_phenotype_closure c
        JOIN q                     USING (hpo_id)
        JOIN hpo_term_ic i         ON i.hpo_id = c.hpo_id
        JOIN disease_phenotype_weight w ON w.disease_id = c.disease_id
        WHERE c.disease_id NOT IN ({placeholders})
        GROUP BY c.disease_id
        HAVING count(*) >= ?
        """,
        [*query_ids, *query_ids, min_shared_terms],
    ).fetchall()

    matches: list[DiseaseMatch] = []
    for disease_id, disease_name, inter_ic, union_ic, shared in rows:
        if disease_id.upper() in excluded:
            continue
        if not union_ic or union_ic <= 0:
            continue
        similarity = float(inter_ic) / float(union_ic)
        if similarity < min_similarity:
            continue
        matches.append(
            DiseaseMatch(
                disease_id=disease_id,
                disease_name=disease_name,
                similarity=round(similarity, 4),
                shared_count=int(shared),
            )
        )

    # Ordinamento con spareggio esplicito sull'identificatore: due malattie con
    # la stessa somiglianza devono comparire nello stesso ordine a ogni run.
    matches.sort(key=lambda m: (-m.similarity, m.disease_id))
    matches = matches[:top_k]

    for m in matches:
        m.shared_phenotypes = _top_shared_phenotypes(
            con, query_ids, m.disease_id, max_shared_listed
        )
        m.orpha_codes = _orpha_codes_for_annotation(con, m.disease_id)
        m.provenance = provenance_for("hpo", "hpo_disease_annotations", record_id=m.disease_id)

    return matches


def _top_shared_phenotypes(
    con: duckdb.DuckDBPyConnection,
    query_ids: list[str],
    other_id: str,
    limit: int,
) -> list[SharedPhenotype]:
    """I fenotipi condivisi piu' informativi.

    Sono cio' che un revisore guarda per decidere se la somiglianza significhi
    qualcosa: un punteggio senza i termini che lo hanno prodotto non e'
    verificabile. Si usano le annotazioni DIRETTE e non la chiusura, perche' un
    antenato generico non aiuta a giudicare.
    """
    placeholders = ", ".join(["?"] * len(query_ids))
    rows = con.execute(
        f"""
        SELECT t.hpo_id, t.name, i.ic
        FROM (SELECT DISTINCT hpo_id FROM disease_phenotypes
              WHERE disease_id IN ({placeholders})) a
        JOIN (SELECT DISTINCT hpo_id FROM disease_phenotypes WHERE disease_id = ?) b
             USING (hpo_id)
        JOIN hpo_terms t   USING (hpo_id)
        JOIN hpo_term_ic i USING (hpo_id)
        ORDER BY i.ic DESC, t.name
        LIMIT ?
        """,
        [*query_ids, other_id, limit],
    ).fetchall()
    return [SharedPhenotype(hpo_id=h, name=n, ic=round(float(ic), 3)) for h, n, ic in rows]
