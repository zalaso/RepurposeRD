"""Test del banco di prova.

Due gruppi. Il primo verifica il confronto fra nomi di farmaco, che sembra un
dettaglio e invece decide la validita' dei numeri: un banco che non riconosce
`LOSARTAN POTASSIUM` come `losartan` misura la denominazione anziche' il metodo.
Il secondo verifica le metriche, incluso il trattamento dei fallimenti attesi.
"""

from __future__ import annotations

import pytest
import yaml

from repurposerd.benchmark import (
    BenchmarkReport,
    CaseResult,
    drug_matches,
    load_cases,
    normalize_drug,
)


class TestConfrontoNomiFarmaco:
    @pytest.mark.parametrize(
        "atteso,candidato",
        [
            ("losartan", "LOSARTAN POTASSIUM"),
            ("cysteamine", "CYSTEAMINE HYDROCHLORIDE"),
            ("lomitapide", "LOMITAPIDE MESYLATE"),
            ("fenofibrate", "FENOFIBRATE MICRONIZED"),
            ("sirolimus", "SIROLIMUS"),
            ("asfotase alfa", "ASFOTASE ALFA"),
        ],
    )
    def test_le_forme_saline_corrispondono(self, atteso, candidato):
        assert drug_matches(atteso, candidato)

    @pytest.mark.parametrize(
        "atteso,candidato",
        [
            # Il caso che conta: un farmaco diverso il cui nome contiene l'altro.
            ("sirolimus", "TEMSIROLIMUS"),
            ("olimus", "SIROLIMUS"),
            ("miglustat", "MIGALASTAT"),
            ("nitisinone", "NITAZOXANIDE"),
        ],
    )
    def test_farmaci_diversi_non_corrispondono(self, atteso, candidato):
        """Una corrispondenza troppo generosa gonfierebbe la copertura con
        farmaci sbagliati, cioe' produrrebbe numeri buoni e falsi."""
        assert not drug_matches(atteso, candidato)

    def test_il_confronto_e_su_parole_intere(self):
        # `alfa` da solo non deve bastare a far corrispondere `asfotase alfa`.
        assert not drug_matches("asfotase alfa", "PEGINTERFERON ALFA")

    def test_normalizzazione(self):
        assert normalize_drug("LOSARTAN POTASSIUM") == "losartan"
        assert normalize_drug("Sirolimus") == "sirolimus"
        assert normalize_drug("") == ""

    def test_stringhe_vuote_non_corrispondono_a_nulla(self):
        assert not drug_matches("", "SIROLIMUS")
        assert not drug_matches("sirolimus", "")


def _res(case_id: str, kind: str, rank: int | None, error: str | None = None) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        disease="d",
        expected_drug="x",
        kind=kind,
        found=rank is not None,
        rank=rank,
        error=error,
    )


class TestMetriche:
    def test_copertura_entro_k(self):
        rep = BenchmarkReport(
            results=[
                _res("a", "repurposing", 1),
                _res("b", "repurposing", 15),
                _res("c", "on_label", None),
            ]
        )
        assert rep.recall_at(10) == (1, 3)
        assert rep.recall_at(20) == (2, 3)

    def test_i_fallimenti_attesi_non_entrano_nella_copertura(self):
        """Contarli fra i trovabili abbasserebbe artificialmente il numero, e
        contarli fra i trovati lo gonfierebbe: restano fuori da entrambi."""
        rep = BenchmarkReport(
            results=[
                _res("a", "repurposing", 1),
                _res("wilson", "structural_miss", None),
            ]
        )
        assert rep.recall_at(40) == (1, 1)

    def test_un_fallimento_atteso_non_trovato_e_un_successo(self):
        assert _res("w", "structural_miss", None).succeeded

    def test_un_fallimento_atteso_trovato_e_un_problema(self):
        """Se comparisse, vorrebbe dire che lo strumento restituisce anche cio'
        che non puo' avere ragione di trovare."""
        assert not _res("w", "structural_miss", 3).succeeded

    def test_posizione_mediana(self):
        rep = BenchmarkReport(
            results=[
                _res("a", "repurposing", 1),
                _res("b", "repurposing", 3),
                _res("c", "repurposing", 11),
            ]
        )
        assert rep.median_rank() == 3

    def test_mediana_assente_se_nessuno_e_trovato(self):
        assert BenchmarkReport(results=[_res("a", "repurposing", None)]).median_rank() is None

    def test_gli_errori_sono_separati_dai_fallimenti(self):
        """Un caso non eseguito non e' un fallimento del metodo: confonderli
        farebbe sembrare peggiore lo strumento per un difetto del banco."""
        rep = BenchmarkReport(results=[_res("a", "repurposing", None, error="malattia ambigua")])
        assert len(rep.errors()) == 1
        assert not rep.errors()[0].succeeded

    def test_scomposizione_per_tipo(self):
        rep = BenchmarkReport(
            results=[
                _res("a", "repurposing", 5),
                _res("b", "on_label", 1),
                _res("c", "on_label", 2),
            ]
        )
        assert rep.recall_at(40, "repurposing") == (1, 1)
        assert rep.recall_at(40, "on_label") == (2, 2)


class TestFileDelBanco:
    """Il banco e' dati curati a mano: le regole del progetto valgono anche qui."""

    def test_il_file_si_carica(self):
        assert load_cases()

    def test_ogni_caso_ha_i_campi_richiesti(self):
        for case in load_cases():
            for campo in ("id", "disease", "expected_drug", "kind"):
                assert campo in case, f"{case.get('id')}: manca {campo}"

    def test_ogni_caso_porta_almeno_una_fonte(self):
        """Stessa regola di config/mechanism.yaml: un'asserzione curata senza
        fonte non vale piu' di un'opinione."""
        for case in load_cases():
            assert case.get("sources"), f"{case['id']} non ha fonti"
            for s in case["sources"]:
                assert str(s).startswith("PMID:"), f"{case['id']}: fonte non riconoscibile: {s}"

    def test_gli_identificativi_sono_unici(self):
        ids = [c["id"] for c in load_cases()]
        assert len(ids) == len(set(ids))

    def test_i_tipi_sono_quelli_previsti(self):
        ammessi = {"repurposing", "on_label", "structural_miss"}
        for case in load_cases():
            assert case["kind"] in ammessi, f"{case['id']}: tipo {case['kind']}"

    def test_il_banco_contiene_casi_che_devono_fallire(self):
        """Un banco in cui tutto e' trovabile premia la promiscuita': si
        alzerebbe la copertura rendendo lo strumento indiscriminato."""
        assert any(c["kind"] == "structural_miss" for c in load_cases())

    def test_il_banco_distingue_riposizionamento_da_indicazione(self):
        """Mescolarli nasconderebbe che il ramo meccanicistico e' molto piu'
        facile del riposizionamento vero."""
        kinds = {c["kind"] for c in load_cases()}
        assert {"repurposing", "on_label"} <= kinds

    def test_le_esclusioni_sono_documentate(self):
        from repurposerd.config import paths

        with (paths().config / "benchmark.yaml").open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        # Le coppie scartate durante la verifica valgono quanto quelle incluse:
        # sono errori gia' commessi, e chi ampliera' il banco deve vederli.
        assert data.get("excluded")
        for voce in data["excluded"]:
            assert voce.get("reason")
