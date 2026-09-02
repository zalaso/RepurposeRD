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


class TestMeccanismoDerivatoDaOrphanet:
    """Orphanet dichiara perdita o guadagno di funzione nel tipo di associazione.

    E' la stessa informazione che `config/mechanism.yaml` conteneva a mano per
    due malattie, gia' presente sul disco per oltre mille, curata dalla fonte e
    sotto CC BY 4.0.
    """

    def _con(self, righe):
        import duckdb

        from repurposerd.store import SCHEMA, bulk_insert

        c = duckdb.connect(":memory:")
        c.execute(SCHEMA)
        bulk_insert(c, "orphanet_gene_assoc", righe)
        return c

    def _riga(self, orpha, gene, tipo):
        return {
            "orpha_code": orpha,
            "gene_symbol": gene,
            "association_type": tipo,
            "is_causal": True,
        }

    LOF = "Disease-causing germline mutation(s) (loss of function) in"
    GOF = "Disease-causing germline mutation(s) (gain of function) in"
    NEUTRO = "Disease-causing germline mutation(s) in"

    def test_perdita_di_funzione(self):
        from repurposerd.pipeline.direction import orphanet_mechanism

        con = self._con([self._riga("ORPHA:1", "GENEA", self.LOF)])
        call = orphanet_mechanism(con, ["ORPHA:1"])
        assert call.mechanism is LOF
        assert call.origin == "orphanet"
        assert call.sources, "deve portare l'identificatore Orphanet come fonte"

    def test_guadagno_di_funzione(self):
        from repurposerd.pipeline.direction import orphanet_mechanism

        con = self._con([self._riga("ORPHA:1", "GENEA", self.GOF)])
        assert orphanet_mechanism(con, ["ORPHA:1"]).mechanism is GOF

    def test_associazione_senza_meccanismo_non_produce_nulla(self):
        """La maggior parte delle voci Orphanet non lo dichiara: dedurlo
        sarebbe inventarlo."""
        from repurposerd.pipeline.direction import orphanet_mechanism

        con = self._con([self._riga("ORPHA:1", "GENEA", self.NEUTRO)])
        assert orphanet_mechanism(con, ["ORPHA:1"]) is None

    def test_annotazioni_in_conflitto_non_si_risolvono_a_maggioranza(self):
        """Se i geni causali portano annotazioni opposte, la direzione resta
        ignota. Un disaccordo fra fonti non si risolve votando: si dichiara."""
        from repurposerd.pipeline.direction import orphanet_mechanism

        con = self._con(
            [
                self._riga("ORPHA:1", "GENEA", self.LOF),
                self._riga("ORPHA:1", "GENEB", self.LOF),
                self._riga("ORPHA:1", "GENEC", self.GOF),
            ]
        )
        assert orphanet_mechanism(con, ["ORPHA:1"]) is None

    def test_senza_codici_orphanet_non_produce_nulla(self):
        from repurposerd.pipeline.direction import orphanet_mechanism

        assert orphanet_mechanism(self._con([]), []) is None


class TestPrecedenzaDellaCurazione:
    """La curazione a mano vince su Orphanet: porta una motivazione leggibile e
    fonti scelte da chi l'ha inserita."""

    def test_il_curato_ha_la_precedenza(self):
        from repurposerd.pipeline.direction import resolve_mechanism

        # La sclerosi tuberosa e' in config/mechanism.yaml.
        call = resolve_mechanism("MONDO:0001734")
        assert call.origin == "curato"
        assert call.mechanism is LOF
        assert call.rationale

    def test_senza_store_resta_la_sola_curazione(self):
        from repurposerd.pipeline.direction import resolve_mechanism

        call = resolve_mechanism("MONDO:9999999")
        assert call.mechanism is UNK
        assert call.origin == "ignoto"

    def test_l_origine_e_sempre_dichiarata(self):
        from repurposerd.pipeline.direction import resolve_mechanism

        for mondo in ("MONDO:0001734", "MONDO:9999999"):
            assert resolve_mechanism(mondo).origin in {"curato", "orphanet", "ignoto"}
