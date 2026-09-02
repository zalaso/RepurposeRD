"""Test del validatore anti-allucinazione.

Sono i test piu' importanti del repository. Descrivono la proprieta' su cui si
regge la credibilita' di tutto lo strumento: una citazione inventata deve essere
una condizione RILEVABILE, non un rischio residuo accettato.

Se qualcuno indebolisce il validatore, questi test devono fallire.
"""

from __future__ import annotations

from repurposerd.llm.validator import validate

KNOWN_GENES = {"GENEA", "GENEB", "GENEZ", "MTOR", "TP53"}
KNOWN_DRUGS = {"farmacox", "farmacoy", "sirolimus"}


def _valid_text() -> str:
    return (
        "FARMACOX agisce su GENEB, annotato insieme a GENEA nel pathway R-HSA-9999999. "
        "La direzione dell'effetto sarebbe coerente con il difetto ipotizzato. "
        "Su PubMed risultano alcuni articoli pertinenti (PMID:22222222). "
        "Si tratta di un'ipotesi meccanicistica, non di una verifica sperimentale."
    )


class TestCitazioniInventate:
    def test_testo_conforme_passa(self, bundle):
        result = validate(
            _valid_text(),
            bundle,
            drug_name="FARMACOX",
            known_genes=KNOWN_GENES,
            known_drugs=KNOWN_DRUGS,
        )
        assert result.ok, result.summary()
        assert result.full_vocabulary

    def test_pmid_inventato_viene_rilevato(self, bundle):
        text = _valid_text() + " Si veda anche PMID:99999999."
        result = validate(text, bundle, drug_name="FARMACOX", known_genes=KNOWN_GENES)
        assert not result.ok
        assert any(v.kind == "unknown_pmid" and "99999999" in v.detail for v in result.violations)

    def test_pmid_nudo_a_otto_cifre_viene_rilevato(self, bundle):
        # Il modello puo' citare senza il prefisso PMID: anche questa forma va colta.
        result = validate(_valid_text() + " Vedi 87654321.", bundle, drug_name="FARMACOX")
        assert not result.ok
        assert any("87654321" in v.detail for v in result.violations)

    def test_identificatore_reactome_inventato_viene_rilevato(self, bundle):
        text = _valid_text() + " Coinvolto anche il pathway R-HSA-1234567."
        result = validate(text, bundle, drug_name="FARMACOX")
        assert not result.ok
        assert any(v.kind == "unknown_identifier" for v in result.violations)

    def test_mondo_inventato_viene_rilevato(self, bundle):
        text = _valid_text() + " La malattia MONDO:0007777 e' correlata."
        result = validate(text, bundle, drug_name="FARMACOX")
        assert not result.ok
        assert any("MONDO:0007777" in v.detail for v in result.violations)

    def test_gene_estraneo_al_bundle_viene_rilevato(self, bundle):
        text = _valid_text() + " Anche GENEZ partecipa al meccanismo."
        result = validate(text, bundle, drug_name="FARMACOX", known_genes=KNOWN_GENES)
        assert not result.ok
        assert any(v.kind == "unknown_gene" and "GENEZ" in v.detail for v in result.violations)

    def test_farmaco_estraneo_al_bundle_viene_rilevato(self, bundle):
        text = _valid_text() + " Un effetto simile e' atteso con sirolimus."
        result = validate(
            text,
            bundle,
            drug_name="FARMACOX",
            known_genes=KNOWN_GENES,
            known_drugs=KNOWN_DRUGS,
        )
        assert not result.ok
        assert any(v.kind == "unknown_drug" for v in result.violations)

    def test_parola_maiuscola_qualsiasi_non_e_un_falso_positivo(self, bundle):
        # "ATTENZIONE" ha la forma di un simbolo genico ma non e' un gene noto.
        text = "ATTENZIONE: " + _valid_text()
        result = validate(text, bundle, drug_name="FARMACOX", known_genes=KNOWN_GENES)
        assert result.ok, result.summary()


class TestLinguaggioVietato:
    def test_affermazione_di_efficacia_viene_bloccata(self, bundle):
        text = _valid_text() + " FARMACOX e' efficace in questa malattia."
        result = validate(text, bundle, drug_name="FARMACOX")
        assert not result.ok
        assert any(v.kind == "forbidden_language" for v in result.violations)

    def test_indicazione_posologica_viene_bloccata(self, bundle):
        text = _valid_text() + " Il dosaggio consigliato e' di 2 mg al giorno."
        result = validate(text, bundle, drug_name="FARMACOX")
        assert not result.ok
        assert any(v.kind == "forbidden_language" for v in result.violations)

    def test_ipotesi_presentata_come_fatto_viene_bloccata(self, bundle):
        text = _valid_text() + " Questo dimostra che il meccanismo e' quello descritto."
        result = validate(text, bundle, drug_name="FARMACOX")
        assert not result.ok
        assert any(v.kind == "overclaim" for v in result.violations)

    def test_lessico_inglese_di_efficacia_viene_bloccato(self, bundle):
        text = _valid_text() + " The drug is clinically proven for this indication."
        result = validate(text, bundle, drug_name="FARMACOX")
        assert not result.ok
        assert any(v.kind == "forbidden_language" for v in result.violations)


class TestSoggetto:
    def test_testo_fuori_tema_viene_rilevato(self, bundle):
        text = "Un paragrafo che non nomina affatto il candidato assegnato."
        result = validate(text, bundle, drug_name="FARMACOX")
        assert not result.ok
        assert any(v.kind == "missing_subject" for v in result.violations)


class TestVocabolariMancanti:
    def test_senza_vocabolari_la_validazione_si_dichiara_parziale(self, bundle):
        result = validate(_valid_text(), bundle, drug_name="FARMACOX")
        assert result.ok
        # Il chiamante deve sapere che il controllo e' stato piu' debole.
        assert not result.full_vocabulary


class TestFalsiPositivi:
    """Il costo di un falso positivo e' un ripiego su un testo corretto.

    Non e' catastrofico, ma degrada l'output senza motivo, e questi casi sono
    emersi controllando i vocabolari reali invece di immaginarli.
    """

    def test_si_non_viene_scambiato_per_un_gene(self, bundle):
        # SI e' un simbolo HGNC approvato (sucrasi-isomaltasi) ed e' anche una
        # parola italiana comunissima. Vedi la nota su GENE_TOKEN_RE.
        text = "SI OSSERVA CHE " + _valid_text()
        result = validate(
            text, bundle, drug_name="FARMACOX", known_genes=KNOWN_GENES | {"SI", "AR", "TF"}
        )
        assert result.ok, result.summary()

    def test_sostantivi_comuni_non_vengono_scambiati_per_farmaci(self, bundle):
        # 'light' e 'calcium' sono nomi di farmaco reali in DGIdb.
        text = _valid_text() + " Il meccanismo coinvolge il calcium intracellulare."
        result = validate(
            text,
            bundle,
            drug_name="FARMACOX",
            known_genes=KNOWN_GENES,
            known_drugs=KNOWN_DRUGS | {"calcium", "light"},
        )
        assert result.ok, result.summary()

    def test_un_gene_inventato_di_lunghezza_ordinaria_resta_rilevabile(self, bundle):
        # La rinuncia sui simboli di due caratteri non deve indebolire il resto.
        text = _valid_text() + " Anche GENEZ partecipa."
        result = validate(text, bundle, drug_name="FARMACOX", known_genes=KNOWN_GENES)
        assert not result.ok
        assert any(v.kind == "unknown_gene" for v in result.violations)


class TestVocabolarioDaCioCheEStatoMostrato:
    """L'invariante e' "puo' citare cio' che gli e' stato mostrato", non
    "cio' che sta nel bundle".

    Il caso e' emerso eseguendo qwen2.5:3b sulla sclerosi tuberosa: il modello
    citava RHEB, che compare nella motivazione curata della coerenza direzionale
    (`TSC1-TSC2 -> RHEB-GTP -> mTORC1`) e quindi gli era stato fornito da noi,
    ma non figurava fra i geni consentiti. Il validatore respingeva generazioni
    corrette per un fatto che eravamo stati noi a dargli.
    """

    def test_un_gene_mostrato_nel_prompt_e_consentito(self, bundle):
        prompt = "La catena e' GENEA -> GENEZ -> GENEB, come da motivazione curata."
        text = _valid_text() + " Il passaggio intermedio coinvolge GENEZ."

        senza = validate(text, bundle, drug_name="FARMACOX", known_genes=KNOWN_GENES)
        assert not senza.ok, "senza contesto GENEZ risulta estraneo"

        con = validate(
            text,
            bundle,
            drug_name="FARMACOX",
            known_genes=KNOWN_GENES,
            shown_context=prompt,
        )
        assert con.ok, con.summary()

    def test_un_gene_non_mostrato_resta_una_violazione(self, bundle):
        # Il rilassamento non deve aprire una falla: cio' che non e' stato
        # mostrato resta vietato.
        prompt = "Nessun gene aggiuntivo in questo contesto."
        text = _valid_text() + " Anche GENEZ partecipa."
        result = validate(
            text,
            bundle,
            drug_name="FARMACOX",
            known_genes=KNOWN_GENES,
            shown_context=prompt,
        )
        assert not result.ok
        assert any(v.kind == "unknown_gene" for v in result.violations)

    def test_un_pmid_non_mostrato_resta_una_violazione(self, bundle):
        prompt = "Contesto senza citazioni bibliografiche."
        result = validate(
            _valid_text() + " Vedi PMID:99999999.",
            bundle,
            drug_name="FARMACOX",
            shown_context=prompt,
        )
        assert not result.ok
        assert any(v.kind == "unknown_pmid" for v in result.violations)

    def test_un_pmid_mostrato_nel_prompt_e_consentito(self, bundle):
        prompt = "Fonte della relazione regolatoria: PMID:12869586."
        result = validate(
            _valid_text() + " La relazione e' documentata (PMID:12869586).",
            bundle,
            drug_name="FARMACOX",
            shown_context=prompt,
        )
        assert result.ok, result.summary()


class TestSovradichiarazioniFlesse:
    """Regressione da un fallimento reale.

    Il testo qui sotto e' stato prodotto davvero da qwen2.5:3b-instruct sul caso
    pilota della sclerosi tuberosa. L'elenco letterale conteneva "conferma che"
    e ha lasciato passare "confermano che": il report ne e' uscito affermando
    che l'ipotesi era "coerente e affidabile", cioe' presentandola come un
    risultato accertato.
    """

    TESTO_REALE = (
        "L'interazione ipotizzata tra il farmaco FARMACOX e la malattia deriva dal "
        "bersaglio del farmaco. L'evidenza raccolta, basata su 313 articoli "
        "scientifici, conferma questa ipotesi. La coerenza direzionale e' stata "
        "confermata. Questi dati confermano che l'interazione ipotizzata tra "
        "FARMACOX e la malattia e' coerente e affidabile."
    )

    def test_il_testo_reale_viene_respinto(self, bundle):
        result = validate(self.TESTO_REALE, bundle, drug_name="FARMACOX")
        assert not result.ok
        assert any(v.kind == "overclaim" for v in result.violations), result.summary()

    def test_confermano_che_viene_intercettato(self, bundle):
        result = validate(
            _valid_text() + " I dati confermano che il meccanismo e' quello descritto.",
            bundle,
            drug_name="FARMACOX",
        )
        assert any(v.kind == "overclaim" for v in result.violations)

    def test_affidabile_viene_intercettato(self, bundle):
        result = validate(
            _valid_text() + " L'ipotesi risulta affidabile.", bundle, drug_name="FARMACOX"
        )
        assert any(v.kind == "overclaim" for v in result.violations)

    def test_forme_flesse_inglesi(self, bundle):
        for frase in (
            " The data confirms that the mechanism holds.",
            " This demonstrates that the drug acts on the pathway.",
            " The association is reliable.",
        ):
            result = validate(_valid_text() + frase, bundle, drug_name="FARMACOX")
            assert any(v.kind == "overclaim" for v in result.violations), frase

    def test_il_linguaggio_ipotetico_corretto_passa(self, bundle):
        # Il rilassamento non deve rendere impossibile scrivere un testo valido.
        buono = (
            _valid_text() + " Il meccanismo sarebbe coerente con il difetto ipotizzato, "
            "ma resta un'ipotesi non verificata sperimentalmente."
        )
        result = validate(buono, bundle, drug_name="FARMACOX", known_genes=KNOWN_GENES)
        assert result.ok, result.summary()


class TestEfficaciaInFormaNominale:
    """Regressione da un fallimento reale del modello GRANDE.

    Il testo qui sotto e' stato prodotto da qwen2.5:7b-instruct sul caso pilota
    della sclerosi tuberosa, ed era passato indenne: l'elenco letterale copriva
    "efficacia dimostrata" e "e' efficace", ma non l'uso nominale
    «il meccanismo ipotizzato per l'efficacia del sirolimus».

    E' la formula piu' insidiosa di tutte, perche' non afferma l'efficacia:
    la presuppone, trattandola come un fatto gia' esistente di cui si discute
    il meccanismo. Un lettore la assorbe senza accorgersene.

    Nota: i modelli grandi non sono immuni. Il 7B sovradichiara meno spesso del
    3B, ma quando lo fa lo fa in modo piu' scorrevole e quindi piu' pericoloso.
    """

    TESTO_REALE_7B = (
        "Il meccanismo ipotizzato per l'efficacia di FARMACOX in questa malattia "
        "deriva dalla sua azione inibitoria su GENEB. L'evidenza raccolta supporta "
        "questa ipotesi, confermando l'interazione inibitoria del farmaco con il "
        "bersaglio. La coerenza del meccanismo e' altamente probabile."
    )

    def test_il_testo_reale_del_7b_viene_respinto(self, bundle):
        result = validate(self.TESTO_REALE_7B, bundle, drug_name="FARMACOX")
        assert not result.ok
        tipi = {v.kind for v in result.violations}
        assert "forbidden_language" in tipi

    def test_efficacia_in_forma_nominale_viene_intercettata(self, bundle):
        for frase in (
            " Studi futuri chiariranno l'efficacia del farmaco.",
            " Non e' nota l'efficacia in questa indicazione.",
            " Il composto risulta poco efficace.",
        ):
            result = validate(_valid_text() + frase, bundle, drug_name="FARMACOX")
            assert not result.ok, frase
            assert any(v.kind == "forbidden_language" for v in result.violations), frase

    def test_confermando_una_conclusione_viene_intercettato(self, bundle):
        result = validate(
            _valid_text() + " I dati supportano l'ipotesi, confermando il meccanismo.",
            bundle,
            drug_name="FARMACOX",
        )
        assert any(v.kind == "overclaim" for v in result.violations)

    def test_altamente_probabile_viene_intercettato(self, bundle):
        result = validate(
            _valid_text() + " La coerenza del meccanismo e' altamente probabile.",
            bundle,
            drug_name="FARMACOX",
        )
        assert any(v.kind == "overclaim" for v in result.violations)

    def test_l_infinito_confermare_resta_permesso(self, bundle):
        """ "Ulteriori studi per confermare" e' prudenza, non sovradichiarazione.

        Vietarlo spingerebbe il modello a scrivere peggio: la frase che invita
        alla verifica sperimentale e' esattamente quella che vogliamo leggere.
        """
        buono = (
            _valid_text() + " Sarebbero necessari ulteriori studi sperimentali per "
            "confermare o smentire questa ipotesi meccanicistica."
        )
        result = validate(buono, bundle, drug_name="FARMACOX", known_genes=KNOWN_GENES)
        assert result.ok, result.summary()

    def test_il_generatore_deterministico_resta_valido(self, candidate, bundle):
        """Il ripiego deve restare sempre disponibile.

        Se il testo deterministico violasse i pattern nuovi, un respingimento
        del modello non avrebbe piu' dove ripiegare.
        """
        from repurposerd.llm.prompts import render_template

        text = render_template(candidate, bundle)
        result = validate(
            text,
            bundle,
            drug_name="FARMACOX",
            known_genes={"GENEA", "GENEB", "GENEZ"},
            known_drugs={"farmacox"},
        )
        assert result.ok, result.summary()


class TestAllineamentoPromptValidatore:
    """Il prompt deve vietare cio' che il validatore rifiuta.

    Se le due liste divergono, il modello viene respinto per una regola che non
    gli e' stata data, e ogni generazione finisce nel ripiego deterministico.

    Non e' teorico: dopo aver bandito la radice `efficac` senza aggiornare il
    prompt, qwen2.5:7b ha fallito la validazione due volte di fila su ogni
    candidato ed e' ripiegato sistematicamente. Il modello stava seguendo le
    istruzioni che aveva; erano le istruzioni a essere incomplete.
    """

    def test_il_prompt_vieta_esplicitamente_le_radici_bandite(self):
        from repurposerd.llm.prompts import SYSTEM_PROMPT

        prompt = SYSTEM_PROMPT.lower()
        for radice in ("efficacia", "efficace", "confermat", "affidabil"):
            assert radice in prompt, (
                f"la radice «{radice}» e' rifiutata dal validatore ma non e' "
                "elencata nel prompt: il modello non puo' rispettarla"
            )

    def test_il_prompt_indica_le_alternative_ammesse(self):
        """Vietare senza offrire un'alternativa produce testo peggiore."""
        from repurposerd.llm.prompts import SYSTEM_PROMPT

        prompt = SYSTEM_PROMPT.lower()
        assert "effetto atteso" in prompt or "plausibilita" in prompt

    def test_il_prompt_non_viola_esso_stesso_i_pattern(self, bundle):
        """Il prompt cita le parole vietate per vietarle.

        Il controllo si applica al testo GENERATO, non al prompt, ma vale la
        pena fissarlo: se un giorno il prompt finisse nel testo validato, il
        fallimento sarebbe incomprensibile.
        """
        from repurposerd.llm.prompts import SYSTEM_PROMPT

        result = validate(SYSTEM_PROMPT, bundle, drug_name=None)
        assert not result.ok, (
            "il prompt contiene le parole vietate per elencarle: se passasse "
            "la validazione, significherebbe che i pattern non funzionano"
        )


class TestConfineSuConfermare:
    """Il divieto su "confermare" guarda l'oggetto, non il verbo.

    Un divieto indiscriminato era stato provato e scartato: con quello,
    qwen2.5:7b falliva la validazione due volte per candidato e ripiegava
    sempre, anche quando scriveva cose corrette. Un validatore che respinge
    tutto non protegge nessuno, rende solo inutile il modello.
    """

    def test_confermata_riferita_ai_dati_e_ammessa(self, bundle):
        """E' un'affermazione sui dati, ed e' vera: otto database la riportano."""
        buono = (
            _valid_text() + " L'interazione farmaco-gene e' confermata da otto "
            "database indipendenti."
        )
        result = validate(buono, bundle, drug_name="FARMACOX", known_genes=KNOWN_GENES)
        assert result.ok, result.summary()

    def test_confermata_riferita_alla_coerenza_e_respinta(self, bundle):
        """La coerenza e' il risultato di un'euristica: nulla la conferma."""
        result = validate(
            _valid_text() + " La coerenza del meccanismo e' confermata.",
            bundle,
            drug_name="FARMACOX",
        )
        assert any(v.kind == "overclaim" for v in result.violations)

    def test_confermata_riferita_all_ipotesi_e_respinta(self, bundle):
        result = validate(
            _valid_text() + " L'ipotesi risulta confermata dalle evidenze raccolte.",
            bundle,
            drug_name="FARMACOX",
        )
        assert any(v.kind == "overclaim" for v in result.violations)

    def test_l_invito_alla_verifica_sperimentale_resta_ammesso(self, bundle):
        """E' la frase che vogliamo leggere: indica cio' che manca."""
        buono = (
            _valid_text() + " Sarebbero necessari ulteriori studi sperimentali per "
            "confermare o smentire il meccanismo ipotizzato."
        )
        result = validate(buono, bundle, drug_name="FARMACOX", known_genes=KNOWN_GENES)
        assert result.ok, result.summary()
