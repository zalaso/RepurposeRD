"""Test del ponte fenotipico.

Si costruisce una piccola ontologia sintetica in memoria invece di usare HPO
reale: il comportamento da verificare e' quello della metrica e delle
esclusioni, non la biologia. Un test che dipendesse dai dati HPO scaricati
fallirebbe a ogni release dell'ontologia per ragioni che non sono difetti.
"""

from __future__ import annotations

import duckdb
import pytest

from repurposerd.pipeline.phenotype import (
    _orpha_codes_for_annotation,
    annotation_ids_for,
    self_match_ids,
    similar_diseases,
)
from repurposerd.store import SCHEMA, bulk_insert, create_indexes

# Ontologia sintetica:
#   HP:1 radice
#     HP:2 comune   (annotato ovunque -> IC quasi nullo)
#     HP:3 raro     (poche malattie -> IC alto)
#     HP:4 raro
#     HP:5 esclusivo di una sola malattia
TERMS = [
    {"hpo_id": "HP:1", "name": "radice"},
    {"hpo_id": "HP:2", "name": "fenotipo comune"},
    {"hpo_id": "HP:3", "name": "fenotipo raro A"},
    {"hpo_id": "HP:4", "name": "fenotipo raro B"},
    {"hpo_id": "HP:5", "name": "fenotipo esclusivo"},
]
EDGES = [
    {"child_id": "HP:2", "parent_id": "HP:1"},
    {"child_id": "HP:3", "parent_id": "HP:1"},
    {"child_id": "HP:4", "parent_id": "HP:1"},
    {"child_id": "HP:5", "parent_id": "HP:1"},
]

# ORPHA:100 e' la query. ORPHA:200 le somiglia molto, ORPHA:300 poco,
# ORPHA:400 condivide solo il fenotipo banale.
ANNOTATIONS = {
    "ORPHA:100": ["HP:2", "HP:3", "HP:4"],
    "ORPHA:200": ["HP:2", "HP:3", "HP:4"],
    "ORPHA:300": ["HP:2", "HP:3"],
    "ORPHA:400": ["HP:2"],
    "ORPHA:500": ["HP:2", "HP:5"],
    "OMIM:900": ["HP:2", "HP:3", "HP:4"],  # duplicato OMIM della query
}


@pytest.fixture
def con():
    """Store sintetico in memoria, con le tabelle derivate gia' calcolate."""
    c = duckdb.connect(":memory:")
    c.execute(SCHEMA)

    bulk_insert(c, "hpo_terms", TERMS)
    bulk_insert(c, "hpo_is_a", EDGES)
    bulk_insert(
        c,
        "disease_phenotypes",
        [
            {"disease_id": d, "disease_name": f"malattia {d}", "hpo_id": h}
            for d, terms in ANNOTATIONS.items()
            for h in terms
        ],
    )

    # Chiusura per transitivita': ogni termine porta con se' la radice.
    closure = {d: {t for h in terms for t in (h, "HP:1")} for d, terms in ANNOTATIONS.items()}
    bulk_insert(
        c,
        "disease_phenotype_closure",
        [{"disease_id": d, "hpo_id": t} for d, ts in closure.items() for t in ts],
    )

    import math

    total = len(closure)
    freq: dict[str, int] = {}
    for ts in closure.values():
        for t in ts:
            freq[t] = freq.get(t, 0) + 1
    ic = {t: -math.log(f / total) for t, f in freq.items()}
    bulk_insert(c, "hpo_term_ic", [{"hpo_id": t, "ic": v} for t, v in ic.items()])
    bulk_insert(
        c,
        "disease_phenotype_weight",
        [
            {
                "disease_id": d,
                "disease_name": f"malattia {d}",
                "total_ic": sum(ic[t] for t in ts),
                "n_terms": len(ts),
            }
            for d, ts in closure.items()
        ],
    )

    # Mondo: la query e il suo duplicato OMIM appartengono allo stesso termine.
    bulk_insert(c, "diseases", [{"mondo_id": "MONDO:0000100", "name": "query"}])
    bulk_insert(
        c,
        "disease_xrefs",
        [
            {"mondo_id": "MONDO:0000100", "xref": "Orphanet:100"},
            {"mondo_id": "MONDO:0000100", "xref": "OMIM:900"},
            {"mondo_id": "MONDO:0000200", "xref": "Orphanet:200"},
        ],
    )
    create_indexes(c)
    yield c
    c.close()


class TestSomiglianza:
    def test_ordina_per_somiglianza_decrescente(self, con):
        ms = similar_diseases(con, ["ORPHA:100"], min_similarity=0.0, min_shared_terms=1)
        ids = [m.disease_id for m in ms]
        # 200 ha lo stesso profilo della query, 400 solo il fenotipo banale.
        assert ids.index("ORPHA:200") < ids.index("ORPHA:300") < ids.index("ORPHA:400")

    def test_profilo_identico_da_somiglianza_massima(self, con):
        ms = similar_diseases(con, ["ORPHA:100"], min_similarity=0.0, min_shared_terms=1)
        top = next(m for m in ms if m.disease_id == "ORPHA:200")
        assert top.similarity == pytest.approx(1.0, abs=1e-6)

    def test_il_fenotipo_banale_non_crea_somiglianza(self, con):
        # ORPHA:400 condivide solo un termine presente in TUTTE le malattie:
        # il suo contenuto informativo e' nullo e non deve produrre somiglianza.
        ms = similar_diseases(con, ["ORPHA:100"], min_similarity=0.0, min_shared_terms=1)
        banale = next(m for m in ms if m.disease_id == "ORPHA:400")
        assert banale.similarity == pytest.approx(0.0, abs=1e-6)

    def test_soglia_minima_di_somiglianza(self, con):
        ms = similar_diseases(con, ["ORPHA:100"], min_similarity=0.5, min_shared_terms=1)
        assert all(m.similarity >= 0.5 for m in ms)
        assert "ORPHA:400" not in [m.disease_id for m in ms]

    def test_soglia_minima_di_termini_condivisi(self, con):
        ms = similar_diseases(con, ["ORPHA:100"], min_similarity=0.0, min_shared_terms=4)
        # Solo chi condivide almeno 4 termini di chiusura sopravvive.
        assert all(m.shared_count >= 4 for m in ms)

    def test_ordinamento_riproducibile(self, con):
        a = [
            m.disease_id
            for m in similar_diseases(con, ["ORPHA:100"], min_similarity=0.0, min_shared_terms=1)
        ]
        b = [
            m.disease_id
            for m in similar_diseases(con, ["ORPHA:100"], min_similarity=0.0, min_shared_terms=1)
        ]
        assert a == b


class TestEsclusioneAutoCorrispondenze:
    def test_il_duplicato_omim_della_query_viene_escluso(self, con):
        """OMIM:900 e' la stessa malattia di ORPHA:100 sotto un altro identificatore.

        Senza esclusione si presenterebbe come la vicina piu' prossima, ed e'
        esattamente cio' che succedeva su Niemann-Pick tipo C.
        """
        excl = self_match_ids(con, "MONDO:0000100")
        assert "OMIM:900" in excl

        ms = similar_diseases(
            con, ["ORPHA:100"], min_similarity=0.0, min_shared_terms=1, exclude_ids=excl
        )
        assert "OMIM:900" not in [m.disease_id for m in ms]

    def test_la_query_stessa_non_compare_mai(self, con):
        ms = similar_diseases(con, ["ORPHA:100"], min_similarity=0.0, min_shared_terms=1)
        assert "ORPHA:100" not in [m.disease_id for m in ms]


class TestMappature:
    def test_annotation_ids_solo_per_malattie_annotate(self, con):
        assert annotation_ids_for(con, ["ORPHA:100"]) == ["ORPHA:100"]
        assert annotation_ids_for(con, ["ORPHA:99999"]) == []
        assert annotation_ids_for(con, []) == []

    def test_orpha_resta_se_stesso(self, con):
        assert _orpha_codes_for_annotation(con, "ORPHA:200") == ["ORPHA:200"]

    def test_omim_viene_ricondotto_via_mondo(self, con):
        # OMIM non e' la fonte dei geni causali di questo progetto: va riportato
        # a Orphanet passando per il termine Mondo che referenzia entrambi.
        assert _orpha_codes_for_annotation(con, "OMIM:900") == ["ORPHA:100"]

    def test_identificatore_non_riconosciuto_non_produce_codici(self, con):
        assert _orpha_codes_for_annotation(con, "DECIPHER:12") == []


class TestFenotipiCondivisi:
    def test_elenca_i_condivisi_piu_informativi(self, con):
        ms = similar_diseases(con, ["ORPHA:100"], min_similarity=0.0, min_shared_terms=1)
        top = next(m for m in ms if m.disease_id == "ORPHA:200")
        nomi = [p.name for p in top.shared_phenotypes]
        # I termini rari devono precedere quello banale: sono cio' che un
        # revisore guarda per decidere se la somiglianza significhi qualcosa.
        assert nomi[0] != "fenotipo comune"
        assert "fenotipo raro A" in nomi

    def test_la_descrizione_e_leggibile(self, con):
        ms = similar_diseases(con, ["ORPHA:100"], min_similarity=0.0, min_shared_terms=1)
        assert "somiglianza" in ms[0].describe()
