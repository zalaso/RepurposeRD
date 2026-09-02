"""Test della serializzazione JSON.

Sostituisce cio' che pydantic garantiva gratis. Le proprieta' verificate qui
sono quelle da cui dipendono l'esportazione dell'evidence bundle e le cache su
disco di PubMed e openFDA: se si rompono, un run perde i dati raccolti o
esporta un bundle non rileggibile.
"""

from __future__ import annotations

import json
from datetime import date

from repurposerd.models import (
    Article,
    DiseaseMechanism,
    Provenance,
    RegulatoryLabel,
)
from repurposerd.serialize import from_jsonable, to_jsonable


class TestConversioneInJson:
    def test_una_dataclass_diventa_un_dizionario(self, provenance):
        d = to_jsonable(provenance)
        assert d["source_id"] == "reactome"
        assert d["license"] == "CC0-1.0"

    def test_le_date_diventano_stringhe_iso(self, provenance):
        assert to_jsonable(provenance)["accessed_at"] == "2026-01-01"

    def test_gli_enum_diventano_il_loro_valore(self):
        assert to_jsonable(DiseaseMechanism.LOSS_OF_FUNCTION) == "loss_of_function"

    def test_i_none_restano_none(self):
        assert to_jsonable(None) is None

    def test_gli_insiemi_diventano_liste_ordinate(self):
        """JSON non ha gli insiemi, e l'ordinamento rende il risultato
        riproducibile: e' una proprieta' che i report dichiarano."""
        assert to_jsonable({"c", "a", "b"}) == ["a", "b", "c"]

    def test_il_risultato_e_serializzabile_davvero(self, bundle):
        # Il test che conta: non basta produrre una struttura, deve passare
        # per json.dumps senza sollevare.
        testo = json.dumps(to_jsonable(bundle), ensure_ascii=False)
        assert '"mondo_id": "MONDO:0000001"' in testo
        assert '"generated_at": "2026-01-01T12:00:00"' in testo

    def test_le_strutture_annidate_vengono_percorse(self, bundle):
        d = to_jsonable(bundle)
        assert d["candidates"][0]["pathway_link"]["pathway"]["reactome_id"] == "R-HSA-9999999"
        assert d["causal_genes"][0]["gene"]["symbol"] == "GENEA"


class TestRicostruzione:
    def test_andata_e_ritorno_su_una_dataclass_piatta(self):
        a = Article(pmid="12345678", title="Titolo", journal="J Test", year=2024)
        assert from_jsonable(Article, to_jsonable(a)) == a

    def test_andata_e_ritorno_con_dataclass_annidata_e_data(self, provenance):
        label = RegulatoryLabel(
            drug_name="FARMACOX",
            label_found=True,
            generic_names=["farmacox"],
            routes=["ORAL"],
            application_numbers=["NDA123456"],
            labeled_indications="indicato per altro",
            matching_labels=3,
            provenance=provenance,
        )
        rifatto = from_jsonable(RegulatoryLabel, to_jsonable(label))
        assert rifatto == label
        assert isinstance(rifatto.provenance, Provenance)
        assert isinstance(rifatto.provenance.accessed_at, date)

    def test_i_campi_assenti_restano_al_default(self):
        """Le cache su disco devono sopravvivere all'aggiunta di un campo nuovo.

        Senza questa tolleranza, ogni modifica al modello invaliderebbe la cache
        di PubMed e openFDA, e ogni riesecuzione ribatterebbe su API pubbliche
        gratuite per dati gia' raccolti.
        """
        a = from_jsonable(Article, {"pmid": "999"})
        assert a.pmid == "999"
        assert a.title is None
        assert a.year is None

    def test_i_campi_ignoti_non_fanno_esplodere(self):
        """Una cache scritta da una versione successiva non deve rompere questa."""
        a = from_jsonable(Article, {"pmid": "999", "campo_del_futuro": 42})
        assert a.pmid == "999"

    def test_gli_enum_si_ricostruiscono(self, bundle):
        d = to_jsonable(bundle)
        assert d["mechanism"] == "loss_of_function"
        assert DiseaseMechanism(d["mechanism"]) is DiseaseMechanism.LOSS_OF_FUNCTION


class TestProprietaCalcolate:
    """Le proprieta' non sono campi: non devono finire nel JSON, e devono
    continuare a funzionare dopo un giro di andata e ritorno."""

    def test_le_proprieta_non_entrano_nel_json(self):
        a = Article(pmid="12345678")
        assert "url" not in to_jsonable(a)

    def test_le_proprieta_funzionano_dopo_la_ricostruzione(self):
        a = from_jsonable(Article, to_jsonable(Article(pmid="12345678")))
        assert a.url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"

    def test_approval_kind_riconosce_il_tipo_di_domanda(self, provenance):
        for numero, atteso in (
            ("NDA020123", "NDA"),
            ("BLA125514", "BLA"),
            ("ANDA201676", "ANDA"),
            ("XX999", None),
        ):
            label = RegulatoryLabel(
                drug_name="X",
                label_found=True,
                application_numbers=[numero],
                provenance=provenance,
            )
            assert label.approval_kind == atteso, numero

    def test_nessun_numero_di_domanda_da_none(self, provenance):
        label = RegulatoryLabel(drug_name="X", label_found=False, provenance=provenance)
        assert label.approval_kind is None


class TestVerificaFontiMancanti:
    """`missing_sources` alimenta `repurposerd doctor`.

    Se sbagliasse, il comando che dovrebbe dire a un nuovo utente cosa manca
    gli direbbe che va tutto bene, e la pipeline fallirebbe piu' avanti con un
    errore molto meno comprensibile.
    """

    def test_una_fonte_mai_scaricata_risulta_mancante(self, tmp_path, monkeypatch):
        from repurposerd import provenance
        from repurposerd.config import Paths

        monkeypatch.setattr(provenance, "paths", lambda: Paths(tmp_path))
        assert provenance.missing_sources([("hgnc", "hgnc_complete_set")]) == [
            "hgnc:hgnc_complete_set"
        ]

    def test_una_voce_nel_manifest_senza_file_su_disco_risulta_mancante(
        self, tmp_path, monkeypatch
    ):
        """Il manifest puo' sopravvivere alla cancellazione di data/raw/."""
        from repurposerd import provenance
        from repurposerd.config import Paths

        monkeypatch.setattr(provenance, "paths", lambda: Paths(tmp_path))
        (tmp_path / "data" / "raw").mkdir(parents=True)
        provenance.save_manifest(
            {"entries": {"hgnc:hgnc_complete_set": {"filename": "assente.txt"}}}
        )
        assert provenance.missing_sources([("hgnc", "hgnc_complete_set")]) == [
            "hgnc:hgnc_complete_set"
        ]

    def test_una_fonte_presente_non_risulta_mancante(self, tmp_path, monkeypatch):
        from repurposerd import provenance
        from repurposerd.config import Paths

        monkeypatch.setattr(provenance, "paths", lambda: Paths(tmp_path))
        raw = tmp_path / "data" / "raw"
        raw.mkdir(parents=True)
        (raw / "presente.txt").write_text("x", encoding="utf-8")
        provenance.save_manifest(
            {"entries": {"hgnc:hgnc_complete_set": {"filename": "presente.txt"}}}
        )
        assert provenance.missing_sources([("hgnc", "hgnc_complete_set")]) == []
