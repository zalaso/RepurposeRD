"""Test del ciclo genera -> valida -> riprova -> ripiega.

Usa backend finti invece di un modello reale: il comportamento del ciclo deve
essere verificabile senza rete, senza GPU e in modo deterministico. Con un
modello vero non si potrebbe scrivere un test che asserisce "al secondo
fallimento ripiega", perche' non si potrebbe garantire che fallisca due volte.

La proprieta' sotto esame e' quella su cui si regge la credibilita' dello
strumento: **un testo che non supera la validazione non finisce mai nel report**.
"""

from __future__ import annotations

import copy

from repurposerd.llm.backend import LLMBackend, LLMUnavailable, TemplateBackend
from repurposerd.llm.narrate import narrate_bundle

VALID_TEXT = (
    "FARMACOX agisce su GENEB, annotato insieme a GENEA nel pathway R-HSA-9999999. "
    "La direzione dell'effetto sarebbe coerente con il difetto ipotizzato. "
    "Su PubMed risultano alcuni articoli pertinenti (PMID:22222222). "
    "Si tratta di un'ipotesi meccanicistica, non di una verifica sperimentale."
)

HALLUCINATED_TEXT = VALID_TEXT + " Si veda anche PMID:99999999."
OVERCLAIMING_TEXT = VALID_TEXT + " FARMACOX e' efficace in questa malattia."

KNOWN_GENES = {"GENEA", "GENEB", "GENEZ"}
KNOWN_DRUGS = {"farmacox", "sirolimus"}


class ScriptedBackend(LLMBackend):
    """Restituisce risposte prestabilite, una per chiamata."""

    name = "scripted"

    def __init__(self, responses: list[str], reachable: bool = True) -> None:
        self.responses = list(responses)
        self.reachable = reachable
        self.calls = 0

    def available(self) -> bool:
        return self.reachable

    def describe(self) -> str:
        return "scripted/test"

    def generate(self, system: str, prompt: str, max_tokens: int = 600) -> str:
        self.calls += 1
        if not self.responses:
            return ""
        return self.responses.pop(0)


class ExplodingBackend(LLMBackend):
    """Simula un endpoint che cade a meta' generazione."""

    name = "exploding"

    def describe(self) -> str:
        return "exploding/test"

    def generate(self, system: str, prompt: str, max_tokens: int = 600) -> str:
        raise LLMUnavailable("connessione interrotta")


class TestGenerazioneRiuscita:
    def test_testo_valido_viene_accettato(self, bundle):
        backend = ScriptedBackend([VALID_TEXT])
        report = narrate_bundle(bundle, backend, KNOWN_GENES, KNOWN_DRUGS)

        assert report.generated == 1
        assert report.fallback == 0
        assert bundle.candidates[0].narrative == VALID_TEXT
        assert backend.calls == 1

    def test_riprova_una_volta_e_accetta_il_secondo_tentativo(self, bundle):
        backend = ScriptedBackend([HALLUCINATED_TEXT, VALID_TEXT])
        report = narrate_bundle(bundle, backend, KNOWN_GENES, KNOWN_DRUGS)

        assert backend.calls == 2
        assert report.generated == 1
        assert report.fallback == 0
        assert bundle.candidates[0].narrative == VALID_TEXT


class TestRipiego:
    def test_due_allucinazioni_portano_al_testo_deterministico(self, bundle):
        backend = ScriptedBackend([HALLUCINATED_TEXT, HALLUCINATED_TEXT])
        report = narrate_bundle(bundle, backend, KNOWN_GENES, KNOWN_DRUGS)

        assert report.fallback == 1
        assert report.generated == 0
        narrative = bundle.candidates[0].narrative
        assert narrative is not None
        # Il PMID inventato non deve sopravvivere in nessuna forma.
        assert "99999999" not in narrative
        assert report.violations, "il motivo del ripiego deve restare tracciato"

    def test_il_linguaggio_di_efficacia_non_arriva_mai_al_report(self, bundle):
        backend = ScriptedBackend([OVERCLAIMING_TEXT, OVERCLAIMING_TEXT])
        narrate_bundle(bundle, backend, KNOWN_GENES, KNOWN_DRUGS)

        narrative = bundle.candidates[0].narrative or ""
        assert "e' efficace" not in narrative.lower()

    def test_backend_irraggiungibile_non_interrompe_il_run(self, bundle):
        backend = ScriptedBackend([VALID_TEXT], reachable=False)
        report = narrate_bundle(bundle, backend, KNOWN_GENES, KNOWN_DRUGS)

        assert backend.calls == 0, "se il backend non risponde non si tenta nemmeno"
        assert report.fallback == 1
        assert bundle.candidates[0].narrative

    def test_errore_a_meta_generazione_ripiega(self, bundle):
        report = narrate_bundle(bundle, ExplodingBackend(), KNOWN_GENES, KNOWN_DRUGS)
        assert report.fallback == 1
        assert bundle.candidates[0].narrative

    def test_risposta_vuota_porta_al_ripiego(self, bundle):
        backend = ScriptedBackend(["", ""])
        report = narrate_bundle(bundle, backend, KNOWN_GENES, KNOWN_DRUGS)
        assert report.fallback == 1
        assert bundle.candidates[0].narrative


class TestBackendTemplate:
    def test_non_chiama_mai_un_modello(self, bundle):
        report = narrate_bundle(bundle, TemplateBackend(), KNOWN_GENES, KNOWN_DRUGS)
        assert report.generated == 0
        assert bundle.candidates[0].narrative
        # Scegliere il generatore deterministico non e' un fallimento del
        # modello, ed e' contato a parte proprio per non farlo sembrare tale.
        assert report.templated_by_design == 1
        assert report.fallback == 0


class TestTrasparenza:
    def test_la_nota_dichiara_la_provenienza_del_testo(self, bundle):
        backend = ScriptedBackend([HALLUCINATED_TEXT, HALLUCINATED_TEXT])
        report = narrate_bundle(bundle, backend, KNOWN_GENES, KNOWN_DRUGS)
        note = report.note()
        # Il lettore deve poter sapere quanto del documento e' stato scritto da un
        # modello, quanto da un template, e quante volte il modello e' stato respinto.
        assert "respinte" in note or "ripieghi" in note

    def test_la_nota_del_template_e_esplicita(self, bundle):
        report = narrate_bundle(bundle, TemplateBackend(), KNOWN_GENES, KNOWN_DRUGS)
        assert "nessun modello linguistico" in report.note()


class TestOrdinamentoRiproducibile:
    """Regressione: i candidati a pari punteggio devono avere un ordine stabile.

    Il bug e' emerso eseguendo la pipeline reale: SIROLIMUS, EVEROLIMUS e
    TEMSIROLIMUS ottengono lo stesso identico punteggio sulla sclerosi tuberosa,
    e senza spareggio esplicito comparivano in ordine diverso a ogni esecuzione.
    """

    def _con_punteggio(self, candidate, nome: str, totale: float):
        c = copy.deepcopy(candidate)
        c.drug_name = nome
        c.score.total = totale
        return c

    def test_pareggi_ordinati_per_nome(self, candidate):
        from repurposerd.pipeline.bundle import rank_candidates

        a = self._con_punteggio(candidate, "TEMSIROLIMUS", 0.758)
        b = self._con_punteggio(candidate, "EVEROLIMUS", 0.758)
        c = self._con_punteggio(candidate, "SIROLIMUS", 0.758)

        assert [x.drug_name for x in rank_candidates([a, b, c])] == [
            "EVEROLIMUS",
            "SIROLIMUS",
            "TEMSIROLIMUS",
        ]

    def test_ordine_di_ingresso_irrilevante(self, candidate):
        from repurposerd.pipeline.bundle import rank_candidates

        a = self._con_punteggio(candidate, "TEMSIROLIMUS", 0.758)
        b = self._con_punteggio(candidate, "EVEROLIMUS", 0.758)
        c = self._con_punteggio(candidate, "SIROLIMUS", 0.758)

        assert [x.drug_name for x in rank_candidates([a, b, c])] == [
            x.drug_name for x in rank_candidates([c, b, a])
        ]

    def test_il_punteggio_resta_il_criterio_primario(self, candidate):
        from repurposerd.pipeline.bundle import rank_candidates

        alto = self._con_punteggio(candidate, "ZZZFARMACO", 0.9)
        basso = self._con_punteggio(candidate, "AAAFARMACO", 0.4)
        assert [x.drug_name for x in rank_candidates([basso, alto])] == [
            "ZZZFARMACO",
            "AAAFARMACO",
        ]


class TestConteggioRespingimenti:
    """`rejected` alimenta la nota di trasparenza del report: se resta a zero,
    il documento dichiara meno respingimenti di quanti ne siano avvenuti."""

    def test_i_respingimenti_vengono_contati(self, bundle):
        backend = ScriptedBackend([HALLUCINATED_TEXT, HALLUCINATED_TEXT])
        report = narrate_bundle(bundle, backend, KNOWN_GENES, KNOWN_DRUGS)
        assert report.rejected == 2

    def test_un_respingimento_seguito_da_successo_viene_contato(self, bundle):
        backend = ScriptedBackend([HALLUCINATED_TEXT, VALID_TEXT])
        report = narrate_bundle(bundle, backend, KNOWN_GENES, KNOWN_DRUGS)
        assert report.rejected == 1
        assert report.generated == 1

    def test_nessun_respingimento_su_testo_valido(self, bundle):
        report = narrate_bundle(bundle, ScriptedBackend([VALID_TEXT]), KNOWN_GENES, KNOWN_DRUGS)
        assert report.rejected == 0


class TestNarrazioneLimitata:
    """`--narrate-top` e' cio' che rende praticabile un modello grande.

    Quaranta candidati con un modello da sette miliardi di parametri su CPU
    sono circa sei ore e mezza. Narrare i primi N e lasciare il resto al
    generatore deterministico riporta il costo nell'ordine dell'ora, senza
    perdere nulla di verificabile.
    """

    def _bundle_con_n_candidati(self, bundle, n: int):
        """N candidati con lo stesso nome del farmaco.

        Il nome resta FARMACOX per tutti di proposito: il testo di prova lo
        menziona, quindi ogni generazione supera la validazione al primo colpo
        e il test misura solo il comportamento del limite, non quello del
        ciclo di riprova che ha gia' i suoi test.
        """
        base = bundle.candidates[0]
        bundle.candidates = [copy.deepcopy(base) for _ in range(n)]
        return bundle

    def test_genera_solo_i_primi_n(self, bundle):
        b = self._bundle_con_n_candidati(bundle, 5)
        backend = ScriptedBackend([VALID_TEXT] * 5)
        report = narrate_bundle(b, backend, KNOWN_GENES, KNOWN_DRUGS, narrate_top=2)

        assert backend.calls == 2, "il modello non deve essere chiamato oltre il limite"
        assert report.generated == 2
        assert report.templated_by_design == 3

    def test_tutti_i_candidati_hanno_comunque_una_spiegazione(self, bundle):
        b = self._bundle_con_n_candidati(bundle, 5)
        narrate_bundle(b, ScriptedBackend([VALID_TEXT] * 5), narrate_top=2)
        assert all(c.narrative for c in b.candidates)

    def test_il_limite_si_applica_ai_primi_in_classifica(self, bundle):
        b = self._bundle_con_n_candidati(bundle, 3)
        narrate_bundle(
            b, ScriptedBackend([VALID_TEXT] * 3), KNOWN_GENES, KNOWN_DRUGS, narrate_top=1
        )
        # Il primo porta il testo del modello, gli altri quello deterministico.
        assert b.candidates[0].narrative == VALID_TEXT
        assert b.candidates[1].narrative != VALID_TEXT
        assert b.candidates[2].narrative != VALID_TEXT

    def test_senza_limite_si_narra_tutto(self, bundle):
        b = self._bundle_con_n_candidati(bundle, 3)
        backend = ScriptedBackend([VALID_TEXT] * 3)
        report = narrate_bundle(b, backend, KNOWN_GENES, KNOWN_DRUGS)
        assert backend.calls == 3
        assert report.templated_by_design == 0

    def test_limite_zero_non_chiama_il_modello(self, bundle):
        b = self._bundle_con_n_candidati(bundle, 3)
        backend = ScriptedBackend([VALID_TEXT] * 3)
        report = narrate_bundle(b, backend, narrate_top=0)
        assert backend.calls == 0
        assert report.templated_by_design == 3

    def test_la_nota_distingue_scelta_da_fallimento(self, bundle):
        b = self._bundle_con_n_candidati(bundle, 4)
        # Il primo viene respinto due volte, gli altri sono oltre il limite.
        backend = ScriptedBackend([HALLUCINATED_TEXT, HALLUCINATED_TEXT])
        report = narrate_bundle(b, backend, KNOWN_GENES, KNOWN_DRUGS, narrate_top=1)
        note = report.note()
        assert "ripieghi" in note, "il fallimento del modello deve restare visibile"
        assert "per scelta" in note, "il limite imposto non deve sembrare un fallimento"


class TestMotiviDeiRespingimenti:
    """Un conteggio senza motivo non informa nessuno.

    Il caso reale: qwen2.5:7b ha scritto "conferma che" su TEMSIROLIMUS, il
    validatore lo ha respinto, il secondo tentativo e' passato. Il report
    dichiarava "1 generazione respinta (motivi: )" — cioe' segnalava che il
    modello aveva provato ad affermare qualcosa di non supportato, senza dire
    cosa.
    """

    def test_il_motivo_sopravvive_a_un_ritentativo_riuscito(self, bundle):
        backend = ScriptedBackend([OVERCLAIMING_TEXT, VALID_TEXT])
        report = narrate_bundle(bundle, backend, KNOWN_GENES, KNOWN_DRUGS)

        assert report.generated == 1, "il secondo tentativo deve essere accettato"
        assert report.rejected == 1
        assert report.violations, "il motivo del respingimento non deve andare perso"
        assert "efficac" in " ".join(report.violations).lower()

    def test_il_motivo_compare_nella_nota(self, bundle):
        backend = ScriptedBackend([OVERCLAIMING_TEXT, VALID_TEXT])
        note = narrate_bundle(bundle, backend, KNOWN_GENES, KNOWN_DRUGS).note()
        assert "respinte" in note
        assert "motivi:" in note
        assert note.count("motivi: )") == 0, "l'elenco dei motivi non puo' essere vuoto"

    def test_nessun_motivo_quando_non_ci_sono_respingimenti(self, bundle):
        report = narrate_bundle(bundle, ScriptedBackend([VALID_TEXT]), KNOWN_GENES, KNOWN_DRUGS)
        assert report.rejected == 0
        assert report.violations == []
