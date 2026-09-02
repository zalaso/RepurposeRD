"""Test della coerenza direzionale.

La tabella di verita' qui sotto e' la regola scientifica centrale dello
strumento. Se cambia il comportamento di questi test, cambia il significato di
ogni riga di ogni report prodotto.
"""

from __future__ import annotations

import pytest

from repurposerd.models import DiseaseMechanism
from repurposerd.pipeline.direction import assess, classify_drug_action, disease_mechanism

LOF = DiseaseMechanism.LOSS_OF_FUNCTION
GOF = DiseaseMechanism.GAIN_OF_FUNCTION
UNK = DiseaseMechanism.UNKNOWN


class TestClassificazioneAzioneFarmaco:
    @pytest.mark.parametrize(
        "types,expected",
        [
            (["inhibitor"], "inhibiting"),
            (["antagonist"], "inhibiting"),
            (["agonist"], "activating"),
            (["inducer"], "activating"),
            (["modulator"], "ambiguous"),
            ([], "ambiguous"),
            (["binder", "other/unknown"], "ambiguous"),
        ],
    )
    def test_tipi_singoli(self, types, expected):
        assert classify_drug_action(types) == expected

    def test_fonti_in_disaccordo_danno_ambiguo(self):
        # Se una fonte dice inibitore e un'altra agonista, il disaccordo e' esso
        # stesso l'informazione: appiattirlo su una delle due sarebbe arbitrario.
        assert classify_drug_action(["inhibitor", "agonist"]) == "ambiguous"


class TestTabellaDiVerita:
    """LoF + arco negativo -> bersaglio iperattivo -> serve un inibitore, e cosi' via."""

    def test_lof_arco_negativo_inibitore_e_coerente(self):
        r = assess(LOF, "TSC2", "MTOR", ["inhibitor"])
        assert r.verdict == "coherent"
        assert r.expected_target_state == "hyperactive"

    def test_lof_arco_negativo_attivatore_e_incoerente(self):
        # Il caso pericoloso: attivare un bersaglio gia' iperattivo.
        r = assess(LOF, "TSC2", "MTOR", ["agonist"])
        assert r.verdict == "incoherent"
        assert r.expected_target_state == "hyperactive"

    def test_hop_zero_lof_attivatore_e_coerente(self):
        # Sul gene causale stesso l'identita' vale come arco positivo:
        # perdita di funzione -> bersaglio ipoattivo -> serve un attivatore.
        r = assess(LOF, "TSC2", "TSC2", ["agonist"])
        assert r.verdict == "coherent"
        assert r.expected_target_state == "hypoactive"

    def test_hop_zero_lof_inibitore_e_incoerente(self):
        r = assess(LOF, "TSC2", "TSC2", ["inhibitor"])
        assert r.verdict == "incoherent"

    def test_hop_zero_gof_inibitore_e_coerente(self):
        r = assess(GOF, "TSC2", "TSC2", ["inhibitor"])
        assert r.verdict == "coherent"
        assert r.expected_target_state == "hyperactive"


class TestDefaultConservativi:
    """`unknown` non e' un esito neutro: e' una lacuna dichiarata."""

    def test_meccanismo_ignoto_da_direzione_ignota(self):
        r = assess(UNK, "TSC2", "MTOR", ["inhibitor"])
        assert r.verdict == "unknown"
        assert "non e' annotato" in r.rationale

    def test_arco_non_curato_da_direzione_ignota(self):
        # GENEA/GENEB non compaiono in config/mechanism.yaml: condividere un
        # pathway non basta, serve il segno della relazione.
        r = assess(LOF, "GENEA", "GENEB", ["inhibitor"])
        assert r.verdict == "unknown"
        assert "segno" in r.rationale

    def test_azione_ambigua_da_direzione_ignota(self):
        r = assess(LOF, "TSC2", "MTOR", ["modulator"])
        assert r.verdict == "unknown"
        # Lo stato atteso resta noto: e' l'azione del farmaco a non esserlo.
        assert r.expected_target_state == "hyperactive"

    def test_la_motivazione_non_e_mai_vuota(self):
        for r in (
            assess(UNK, "A", "B", ["inhibitor"]),
            assess(LOF, "A", "B", ["inhibitor"]),
            assess(LOF, "TSC2", "MTOR", ["inhibitor"]),
        ):
            assert r.rationale.strip(), "ogni esito deve poter essere spiegato a un revisore"


class TestMeccanismoCurato:
    def test_malattia_non_annotata_e_ignota(self):
        mech, rationale, sources = disease_mechanism("MONDO:9999999")
        assert mech is UNK
        assert rationale is None
        assert sources == []

    def test_tsc_e_annotata_come_perdita_di_funzione(self):
        mech, rationale, sources = disease_mechanism("MONDO:0001734")
        assert mech is LOF
        assert rationale
        # Un'asserzione curata a mano senza fonte non ha valore piu' di un'opinione.
        assert sources


class TestGenePresoInPrestito:
    """Un gene raggiunto per somiglianza fenotipica appartiene a un'altra malattia.

    Applicargli il meccanismo curato della malattia interrogata significherebbe
    asserire una coerenza direzionale su un presupposto mai verificato: perdita
    o guadagno di funzione sono proprieta' di una coppia gene-malattia, non del
    gene da solo.
    """

    def test_la_motivazione_spiega_il_prestito(self):
        r = assess(UNK, "SMPD1", "UGCG", ["inhibitor"], borrowed_gene=True)
        assert r.verdict == "unknown"
        assert "somiglianza fenotipica" in r.rationale
        assert "non si trasferisce" in r.rationale

    def test_senza_prestito_la_motivazione_resta_quella_dell_annotazione(self):
        r = assess(UNK, "GENEA", "GENEB", ["inhibitor"], borrowed_gene=False)
        assert "mechanism.yaml" in r.rationale
        assert "somiglianza fenotipica" not in r.rationale

    def test_il_verdetto_e_sempre_ignoto_per_un_gene_in_prestito(self):
        # Anche con un arco curato, il chiamante passa UNKNOWN come meccanismo:
        # qui si verifica che l'esito resti prudente.
        r = assess(UNK, "TSC2", "MTOR", ["inhibitor"], borrowed_gene=True)
        assert r.verdict == "unknown"
