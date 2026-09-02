"""Test della conferma regolatoria openFDA.

Si verifica la trasformazione della risposta, non la rete: un test che
interrogasse davvero l'API fallirebbe offline e a ogni modifica del catalogo
FDA, per ragioni che non sono difetti del codice. I campioni riproducono la
struttura reale della risposta, verificata sull'API.
"""

from __future__ import annotations

from repurposerd.models import Candidate, RegulatoryLabel
from repurposerd.report.render import _regulatory_lines, render_report
from repurposerd.sources.openfda import MAX_INDICATION_CHARS, _to_label

# Ritaglio della risposta reale per sirolimus.
RISPOSTA_FDA = {
    "result": {
        "indications_and_usage": [
            "1 INDICATIONS AND USAGE Sirolimus is an mTOR inhibitor immunosuppressant "
            "indicated for the prophylaxis of organ rejection in patients aged 13 years "
            "or older receiving renal transplants."
        ],
        "openfda": {
            "generic_name": ["SIROLIMUS"],
            "brand_name": ["sirolimus", "RAPAMUNE"],
            "route": ["ORAL"],
            "application_number": ["ANDA201676"],
        },
    },
    "total": 26,
}


class TestTrasformazioneRisposta:
    def test_etichetta_trovata(self, provenance):
        label = _to_label("SIROLIMUS", RISPOSTA_FDA, provenance)
        assert label.label_found
        assert label.generic_names == ["SIROLIMUS"]
        assert label.routes == ["ORAL"]
        assert label.approval_kind == "ANDA"
        assert label.matching_labels == 26

    def test_le_indicazioni_vengono_normalizzate(self, provenance):
        label = _to_label("SIROLIMUS", RISPOSTA_FDA, provenance)
        assert label.labeled_indications
        assert "prophylaxis of organ rejection" in label.labeled_indications
        # Gli a capo dell'etichetta originale non devono finire nel report.
        assert "\n" not in label.labeled_indications

    def test_le_indicazioni_vengono_troncate(self, provenance):
        lungo = {
            "result": {"indications_and_usage": ["x " * 2000], "openfda": {}},
            "total": 1,
        }
        label = _to_label("X", lungo, provenance)
        assert label.labeled_indications is not None
        # Si conserva un estratto: serve a far capire per cosa il farmaco sia
        # etichettato, non a riprodurre il foglietto illustrativo.
        assert len(label.labeled_indications) <= MAX_INDICATION_CHARS + 3

    def test_nessuna_etichetta(self, provenance):
        label = _to_label("FARMACO INESISTENTE", None, provenance)
        assert not label.label_found
        assert label.labeled_indications is None
        assert label.generic_names == []

    def test_ogni_etichetta_porta_la_provenienza(self, provenance):
        for hit in (RISPOSTA_FDA, None):
            assert _to_label("X", hit, provenance).provenance is provenance


class TestResaNelReport:
    def _con_etichetta(self, candidate: Candidate, label: RegulatoryLabel) -> Candidate:
        import copy

        c = copy.deepcopy(candidate)
        c.regulatory = label
        return c

    def test_le_indicazioni_sono_marcate_come_altre_malattie(self, candidate, provenance):
        """E' il punto dell'intera integrazione: rendere evidente che
        l'ipotesi e' fuori indicazione."""
        label = _to_label("SIROLIMUS", RISPOSTA_FDA, provenance)
        righe = " ".join(_regulatory_lines(self._con_etichetta(candidate, label)))
        assert "NON questa malattia" in righe
        assert "prophylaxis of organ rejection" in righe

    def test_l_assenza_di_etichetta_non_viene_letta_come_non_approvato(self, candidate, provenance):
        """openFDA copre solo gli Stati Uniti: molti farmaci per malattie rare
        sono autorizzati solo da EMA, e il report non deve suggerire il contrario."""
        label = _to_label("MIGLUSTAT", None, provenance)
        righe = " ".join(_regulatory_lines(self._con_etichetta(candidate, label)))
        assert "extra-USA" in righe
        assert "non approvato" not in righe.lower()

    def test_l_assenza_segnala_la_discordanza_con_dgidb(self, candidate, provenance):
        """Nel caso pilota Niemann-Pick il candidato in prima posizione risultava
        approvato secondo DGIdb e privo di qualunque etichetta FDA."""
        label = _to_label("GENISTEIN", None, provenance)
        righe = " ".join(_regulatory_lines(self._con_etichetta(candidate, label)))
        assert "DGIdb" in righe

    def test_senza_conferma_regolatoria_non_si_stampa_nulla(self, candidate):
        assert _regulatory_lines(candidate) == []

    def test_il_report_completo_include_l_etichetta(self, bundle, candidate, provenance):
        label = _to_label("SIROLIMUS", RISPOSTA_FDA, provenance)
        bundle.candidates = [self._con_etichetta(candidate, label)]
        md = render_report(bundle)
        assert "Etichetta FDA" in md
        assert "Indicazioni etichettate" in md


class TestNonEntraNelPunteggio:
    """openFDA copre gli Stati Uniti. Se entrasse nello score, penalizzerebbe i
    farmaci approvati solo altrove: miglustat e' autorizzato da EMA per
    Niemann-Pick tipo C, indicazione che l'FDA non ha mai concesso."""

    def test_il_punteggio_non_ha_una_componente_regolatoria(
        self, link, interaction, assessment, literature
    ):
        from repurposerd.pipeline.scoring import score_candidate

        componenti = score_candidate(link, interaction, assessment, literature).components
        assert not any("regulat" in k or "fda" in k for k in componenti)

    def test_la_presenza_di_etichetta_non_cambia_il_punteggio(
        self, candidate, link, interaction, assessment, literature, provenance
    ):
        from repurposerd.pipeline.scoring import score_candidate

        prima = score_candidate(link, interaction, assessment, literature).total
        candidate.regulatory = _to_label("SIROLIMUS", RISPOSTA_FDA, provenance)
        dopo = score_candidate(link, interaction, assessment, literature).total
        assert prima == dopo
