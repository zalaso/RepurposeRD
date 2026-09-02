"""Test della risoluzione malattia -> identificatore canonico -> gene causale.

Store sintetico in memoria: i casi da verificare sono l'ambiguita', la discesa
ai sottotipi e il filtro sulle associazioni causali, non i dati reali. Un test
che dipendesse dalle release di Mondo e Orphanet fallirebbe a ogni loro
aggiornamento per ragioni che non sono difetti del codice.
"""

from __future__ import annotations

import duckdb
import pytest

from repurposerd.pipeline.resolve import (
    AmbiguousDisease,
    DiseaseNotFound,
    causal_genes_for,
    resolve,
    resolve_disease,
)
from repurposerd.store import SCHEMA, bulk_insert, create_indexes

DISEASES = [
    {"mondo_id": "MONDO:0000001", "name": "malattia alfa"},
    {"mondo_id": "MONDO:0000002", "name": "malattia beta"},
    {"mondo_id": "MONDO:0000003", "name": "malattia beta, forma infantile"},
    {"mondo_id": "MONDO:0000004", "name": "malattia beta, forma adulta"},
    {"mondo_id": "MONDO:0000005", "name": "sindrome duplicata"},
    {"mondo_id": "MONDO:0000006", "name": "sindrome duplicata"},
]

XREFS = [
    {"mondo_id": "MONDO:0000001", "xref": "Orphanet:111"},
    {"mondo_id": "MONDO:0000001", "xref": "OMIM:600001"},
    # 'beta' padre: nessun gene proprio, i geni stanno sui sottotipi.
    {"mondo_id": "MONDO:0000002", "xref": "Orphanet:222"},
    {"mondo_id": "MONDO:0000003", "xref": "Orphanet:333"},
    {"mondo_id": "MONDO:0000004", "xref": "Orphanet:444"},
]

IS_A = [
    {"child_id": "MONDO:0000003", "parent_id": "MONDO:0000002"},
    {"child_id": "MONDO:0000004", "parent_id": "MONDO:0000002"},
]

SYNONYMS = [{"mondo_id": "MONDO:0000001", "synonym": "sindrome di prova"}]

GENES = [
    {"symbol": "GENEA", "hgnc_id": "HGNC:1", "entrez_id": 101, "uniprot_ids": "P1|P2"},
    {"symbol": "GENEB", "hgnc_id": "HGNC:2", "entrez_id": 102},
    {"symbol": "GENEMOD", "hgnc_id": "HGNC:3", "entrez_id": 103},
]

ORPHANET = [
    {
        "orpha_code": "ORPHA:111",
        "disorder_name": "malattia alfa",
        "gene_symbol": "GENEA",
        "association_type": "Disease-causing germline mutation(s) in",
        "is_causal": True,
        "pmids": "1111111,2222222",
    },
    {
        # Modificatore: reale, ma non causale. Deve restare fuori.
        "orpha_code": "ORPHA:111",
        "disorder_name": "malattia alfa",
        "gene_symbol": "GENEMOD",
        "association_type": "Modifying germline mutation in",
        "is_causal": False,
    },
    {
        # Il gene di 'beta' vive sul sottotipo, non sul padre.
        "orpha_code": "ORPHA:333",
        "disorder_name": "malattia beta, forma infantile",
        "gene_symbol": "GENEB",
        "association_type": "Disease-causing germline mutation(s) in",
        "is_causal": True,
    },
]


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    c.execute(SCHEMA)
    bulk_insert(c, "diseases", DISEASES)
    bulk_insert(c, "disease_xrefs", XREFS)
    bulk_insert(c, "disease_is_a", IS_A)
    bulk_insert(c, "disease_synonyms", SYNONYMS)
    bulk_insert(c, "genes", GENES)
    bulk_insert(c, "orphanet_gene_assoc", ORPHANET)
    create_indexes(c)
    yield c
    c.close()


class TestRisoluzioneIdentificatori:
    def test_mondo_diretto(self, con):
        d = resolve_disease(con, "MONDO:0000001")
        assert d.label == "malattia alfa"

    def test_mondo_insensibile_al_caso(self, con):
        assert resolve_disease(con, "mondo:0000001").mondo_id == "MONDO:0000001"

    def test_da_codice_orphanet(self, con):
        assert resolve_disease(con, "ORPHA:111").mondo_id == "MONDO:0000001"
        assert resolve_disease(con, "Orphanet:111").mondo_id == "MONDO:0000001"

    def test_da_codice_omim(self, con):
        assert resolve_disease(con, "OMIM:600001").mondo_id == "MONDO:0000001"

    def test_xref_normalizzati_nel_risultato(self, con):
        d = resolve_disease(con, "MONDO:0000001")
        assert d.orpha_codes == ["ORPHA:111"]
        assert d.omim_ids == ["OMIM:600001"]


class TestRisoluzioneTestuale:
    def test_nome_esatto(self, con):
        assert resolve_disease(con, "malattia alfa").mondo_id == "MONDO:0000001"

    def test_nome_insensibile_al_caso_e_agli_spazi(self, con):
        assert resolve_disease(con, "  MALATTIA ALFA  ").mondo_id == "MONDO:0000001"

    def test_sinonimo_esatto(self, con):
        assert resolve_disease(con, "sindrome di prova").mondo_id == "MONDO:0000001"

    def test_sottostringa_quando_univoca(self, con):
        assert resolve_disease(con, "alfa").mondo_id == "MONDO:0000001"

    def test_malattia_inesistente(self, con):
        with pytest.raises(DiseaseNotFound):
            resolve_disease(con, "malattia che non esiste")


class TestAmbiguita:
    """L'ambiguita' e' un errore, non qualcosa da risolvere a caso.

    Scegliere silenziosamente fra due malattie simili e' il modo piu' rapido per
    produrre un report perfettamente formattato e completamente sbagliato.
    """

    def test_nome_condiviso_da_due_termini(self, con):
        with pytest.raises(AmbiguousDisease):
            resolve_disease(con, "sindrome duplicata")

    def test_sottostringa_che_corrisponde_a_piu_malattie(self, con):
        with pytest.raises(AmbiguousDisease):
            resolve_disease(con, "beta")

    def test_l_errore_elenca_le_alternative(self, con):
        with pytest.raises(AmbiguousDisease) as exc:
            resolve_disease(con, "beta")
        messaggio = str(exc.value)
        # Un errore che non dice come uscirne e' un vicolo cieco.
        assert "MONDO:0000002" in messaggio
        assert "identificatore preciso" in messaggio


class TestGeniCausali:
    def test_solo_associazioni_causali(self, con):
        d = resolve_disease(con, "MONDO:0000001")
        simboli = [c.gene.symbol for c in causal_genes_for(con, d)]
        assert simboli == ["GENEA"]
        assert "GENEMOD" not in simboli, "un modificatore non e' una causa"

    def test_pmid_di_validazione_propagati(self, con):
        d = resolve_disease(con, "MONDO:0000001")
        cg = causal_genes_for(con, d)[0]
        assert cg.validation_pmids == ["1111111", "2222222"]

    def test_dati_del_gene_arricchiti_da_hgnc(self, con):
        d = resolve_disease(con, "MONDO:0000001")
        cg = causal_genes_for(con, d)[0]
        assert cg.gene.entrez_id == 101
        assert cg.gene.uniprot_ids == ["P1", "P2"]

    def test_ogni_gene_causale_porta_la_provenienza(self, con):
        d = resolve_disease(con, "MONDO:0000001")
        cg = causal_genes_for(con, d)[0]
        assert cg.provenance.source_id == "orphanet"
        assert cg.provenance.record_id == "ORPHA:111/GENEA"


class TestDiscesaAiSottotipi:
    """Orphanet colloca spesso il gene sui sottotipi clinici, non sul padre.

    Niemann-Pick tipo C e' il caso reale: ORPHA:646 non porta alcun gene,
    mentre le sue forme cliniche riportano tutte NPC1 e NPC2. Senza questa
    discesa lo strumento fallirebbe proprio sulle malattie descritte in modo
    piu' accurato.
    """

    def test_il_padre_eredita_i_geni_dei_sottotipi(self, con):
        d = resolve_disease(con, "MONDO:0000002")  # nessun gene proprio
        simboli = [c.gene.symbol for c in causal_genes_for(con, d)]
        assert simboli == ["GENEB"]

    def test_la_discesa_non_scatta_se_il_padre_ha_geni_propri(self, con):
        # 'alfa' ha un gene proprio: non deve andare a cercarne altrove.
        d = resolve_disease(con, "MONDO:0000001")
        assert [c.gene.symbol for c in causal_genes_for(con, d)] == ["GENEA"]

    def test_nessun_gene_se_non_ce_ne_sono_da_nessuna_parte(self, con):
        d = resolve_disease(con, "MONDO:0000005")
        assert causal_genes_for(con, d) == []


class TestResolveCompleto:
    def test_restituisce_malattia_e_geni_insieme(self, con):
        r = resolve(con, "malattia alfa")
        assert r.disease.mondo_id == "MONDO:0000001"
        assert [c.gene.symbol for c in r.causal_genes] == ["GENEA"]

    def test_nessun_duplicato_fra_i_geni(self, con):
        r = resolve(con, "MONDO:0000002")
        simboli = [c.gene.symbol for c in r.causal_genes]
        assert len(simboli) == len(set(simboli))
