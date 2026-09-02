"""Test dello scoring e del report.

Verificano due proprieta' che il progetto promette esplicitamente:
  - il punteggio e' scomponibile e ogni componente e' visibile
  - il disclaimer non e' rimovibile per distrazione
"""

from __future__ import annotations

import copy

import pytest

from repurposerd.llm.prompts import candidate_facts, render_template
from repurposerd.pipeline.scoring import (
    _component_pathway_specificity,
    score_candidate,
    tier_for,
)
from repurposerd.report.render import render_report


class TestSpecificitaPathway:
    def test_pathway_piccolo_batte_pathway_grande(self, link, pathway):
        pathway.size = 5
        small = _component_pathway_specificity(link)
        pathway.size = 180
        large = _component_pathway_specificity(link)
        assert small > large

    def test_pathway_al_limite_non_porta_informazione(self, link, pathway):
        pathway.size = 200  # pari a max_pathway_size in config/scoring.yaml
        assert _component_pathway_specificity(link) == 0.0

    def test_valore_sempre_nel_dominio(self, link, pathway):
        for size in (1, 2, 7, 50, 199, 200, 5000):
            pathway.size = size
            assert 0.0 <= _component_pathway_specificity(link) <= 1.0


class TestPunteggio:
    def test_ogni_componente_e_esposta(self, link, interaction, assessment, literature):
        breakdown = score_candidate(link, interaction, assessment, literature)
        assert set(breakdown.components) == {
            "pathway_proximity",
            "pathway_specificity",
            "direction_coherence",
            "interaction_support",
            "literature_support",
            "route_directness",
        }

    def test_il_totale_e_la_somma_dei_contributi(self, link, interaction, assessment, literature):
        breakdown = score_candidate(link, interaction, assessment, literature)
        assert breakdown.total == pytest.approx(sum(breakdown.contributions().values()), abs=1e-3)

    def test_direzione_incoerente_penalizza(self, link, interaction, assessment, literature):
        coherent = score_candidate(link, interaction, assessment, literature).total
        assessment.verdict = "incoherent"
        incoherent = score_candidate(link, interaction, assessment, literature).total
        assert incoherent < coherent

    def test_direzione_ignota_sta_fra_le_due(self, link, interaction, assessment, literature):
        coherent = score_candidate(link, interaction, assessment, literature).total
        assessment.verdict = "unknown"
        unknown = score_candidate(link, interaction, assessment, literature).total
        assessment.verdict = "incoherent"
        incoherent = score_candidate(link, interaction, assessment, literature).total
        # 'unknown' non e' neutro: costa, ma meno di una direzione sbagliata.
        assert incoherent < unknown < coherent

    def test_hop_maggiore_penalizza(self, link, interaction, assessment, literature):
        link.hops = 0
        near = score_candidate(link, interaction, assessment, literature).total
        link.hops = 2
        far = score_candidate(link, interaction, assessment, literature).total
        assert far < near


class TestLivelliDiEvidenza:
    def test_nessun_livello_si_chiama_forte(self):
        # Il vocabolario non deve offrire una parola leggibile come efficacia.
        names = {tier_for(s)[0] for s in (0.0, 0.2, 0.3, 0.5, 0.7, 0.9, 1.0)}
        assert not any("forte" in n.lower() or "strong" in n.lower() for n in names)

    def test_punteggio_basso_alza_sempre_il_flag(self):
        for score in (0.0, 0.1, 0.3, 0.44):
            _name, weak = tier_for(score)
            assert weak, f"punteggio {score} deve portare il flag di evidenza debole"

    def test_livello_monotono(self):
        assert tier_for(0.9)[0] == tier_for(0.66)[0]
        assert tier_for(0.1)[0] != tier_for(0.9)[0]


class TestReport:
    def test_disclaimer_in_apertura_e_in_chiusura(self, bundle):
        md = render_report(bundle)
        assert md.count("NON SONO CONSIGLI MEDICI") >= 2, (
            "il disclaimer deve comparire sia in testa sia in coda: "
            "un lettore puo' leggere solo una delle due"
        )

    def test_il_report_non_promette_efficacia(self, bundle):
        md = render_report(bundle).lower()
        for phrase in ("e' efficace", "efficacia dimostrata", "cura la malattia", "guarigione"):
            assert phrase not in md

    def test_ogni_candidato_porta_le_sue_fonti(self, bundle):
        md = render_report(bundle)
        assert "PMID:22222222" in md
        assert "R-HSA-9999999" in md
        assert "Reactome" in md

    def test_direzione_incoerente_e_segnalata_visibilmente(self, bundle):
        bundle.candidates[0].direction.verdict = "incoherent"
        md = render_report(bundle)
        assert "CAUTION" in md
        assert "incoerente" in md.lower()

    def test_evidenza_debole_e_segnalata(self, bundle):
        bundle.candidates[0].weak_evidence_flag = True
        md = render_report(bundle)
        assert "Evidenza" in md and "NOTE" in md

    def test_report_vuoto_resta_valido(self, bundle):
        bundle.candidates = []
        md = render_report(bundle)
        assert "Nessun candidato" in md
        assert "NON SONO CONSIGLI MEDICI" in md


class TestPromptEtemplate:
    def test_i_fatti_passati_al_modello_non_contengono_altro(self, candidate, bundle):
        facts = candidate_facts(candidate, bundle)
        # Il modello non deve ricevere nulla che non sia gia' verificato.
        assert facts["farmaco_candidato"] == "FARMACOX"
        assert facts["geni_causali"] == ["GENEA"]
        assert "punteggio" in facts

    def test_il_template_cita_solo_cio_che_esiste(self, candidate, bundle):
        from repurposerd.llm.validator import validate

        text = render_template(candidate, bundle)
        result = validate(
            text,
            bundle,
            drug_name="FARMACOX",
            known_genes={"GENEA", "GENEB", "GENEZ"},
            known_drugs={"farmacox", "sirolimus"},
        )
        assert result.ok, f"il generatore deterministico non deve mai violare: {result.summary()}"

    def test_il_template_dichiara_la_direzione_ignota(self, candidate, bundle):
        candidate.direction.verdict = "unknown"
        text = render_template(candidate, bundle).lower()
        assert "non e' determinabile" in text or "non determinabile" in text


class TestPonteFenotipico:
    """Un candidato indiretto non deve competere alla pari con uno diretto,
    e il lettore deve poter vedere la differenza senza cercarla."""

    def _con_ponte(self, candidate, similarity: float = 0.20):
        from repurposerd.models import PhenotypeBridge, Provenance

        c = copy.deepcopy(candidate)
        c.pathway_link.bridge = PhenotypeBridge(
            source_disease_id="ORPHA:999",
            source_disease_name="malattia somigliante",
            similarity=similarity,
            shared_phenotypes=["atassia", "epatomegalia"],
            borrowed_gene="GENEA",
            provenance=Provenance(source_id="hpo", source_name="HPO", license="propria HPO"),
        )
        return c

    def test_il_ponte_penalizza_il_punteggio(
        self, candidate, link, interaction, assessment, literature
    ):
        diretto = score_candidate(link, interaction, assessment, literature).total
        c = self._con_ponte(candidate)
        indiretto = score_candidate(c.pathway_link, interaction, assessment, literature).total
        assert indiretto < diretto

    def test_la_penalita_scala_con_la_somiglianza(
        self, candidate, interaction, assessment, literature
    ):
        debole = score_candidate(
            self._con_ponte(candidate, 0.15).pathway_link, interaction, assessment, literature
        ).total
        forte = score_candidate(
            self._con_ponte(candidate, 0.80).pathway_link, interaction, assessment, literature
        ).total
        assert debole < forte

    def test_il_report_marca_il_candidato_indiretto(self, bundle, candidate):
        bundle.candidates = [self._con_ponte(candidate)]
        md = render_report(bundle)
        assert "IMPORTANT" in md
        assert "ponte fenotipico" in md.lower()
        assert "malattia somigliante" in md
        # I fenotipi che hanno prodotto l'accostamento devono essere visibili:
        # un punteggio senza i termini che lo hanno generato non e' verificabile.
        assert "atassia" in md

    def test_la_tabella_distingue_diretto_da_ponte(self, bundle, candidate):
        bundle.candidates = [self._con_ponte(candidate)]
        md = render_report(bundle)
        assert "| ponte |" in md

        bundle.candidates = [candidate]
        md = render_report(bundle)
        assert "| diretto |" in md

    def test_il_template_dichiara_il_ponte(self, bundle, candidate):
        from repurposerd.llm.validator import validate

        c = self._con_ponte(candidate)
        bundle.candidates = [c]
        text = render_template(c, bundle)
        assert "non deriva dal gene causale" in text
        assert "somiglianza clinica non dimostra" in text
        # E deve comunque restare validabile.
        result = validate(
            text,
            bundle,
            drug_name="FARMACOX",
            known_genes={"GENEA", "GENEB", "GENEZ"},
            known_drugs={"farmacox"},
        )
        assert result.ok, result.summary()


class TestSelezionePerLetteratura:
    """Regressione: il pre-filtro non deve poter scartare un candidato che la
    componente omessa avrebbe promosso sopra la soglia."""

    def _scored(self, candidate, valori):
        out = []
        for i, v in enumerate(valori):
            c = copy.deepcopy(candidate)
            c.drug_name = f"FARMACO{i:03d}"
            c.score.total = v
            out.append((v, c))
        return out

    def test_include_tutti_entro_il_margine_della_letteratura(self, candidate):
        from repurposerd.config import scoring_config
        from repurposerd.pipeline.bundle import _literature_shortlist

        cfg = scoring_config()
        peso = cfg["weights"]["literature_support"]
        # Il terzo vale 0.50; con margine 0.10 la soglia e' 0.40.
        valori = [0.60, 0.55, 0.50, 0.45, 0.41, 0.39, 0.20]
        short, truncated = _literature_shortlist(self._scored(candidate, valori), top_n=3, cfg=cfg)

        assert not truncated
        inclusi = [t for t, _ in short]
        assert 0.41 in inclusi, "un candidato entro il margine non puo' essere escluso"
        assert 0.39 not in inclusi, "oltre il margine non puo' superare la soglia"
        assert min(inclusi) >= 0.50 - peso

    def test_segnala_il_troncamento(self, candidate, monkeypatch):
        from repurposerd.config import scoring_config
        from repurposerd.pipeline.bundle import _literature_shortlist

        cfg = dict(scoring_config())
        cfg["filters"] = {**cfg["filters"], "literature_shortlist_cap": 2}
        short, truncated = _literature_shortlist(
            self._scored(candidate, [0.6, 0.58, 0.56, 0.54]), top_n=1, cfg=cfg
        )
        assert truncated, "quando il tetto taglia, il chiamante deve poterlo dire"
        assert len(short) == 2

    def test_lista_vuota_non_esplode(self, candidate):
        from repurposerd.config import scoring_config
        from repurposerd.pipeline.bundle import _literature_shortlist

        assert _literature_shortlist([], top_n=5, cfg=scoring_config()) == ([], False)


class TestTettoSenzaDirezione:
    """Non si puo' chiamare "moderata" un'evidenza di cui non si sa se il
    farmaco correggerebbe o aggraverebbe il difetto.

    Il caso reale: ASPIRIN -> TSC1 nel pilota della sclerosi tuberosa. E' un
    artefatto di aggregazione di DGIdb, ha un punteggio alto perche' colpisce
    direttamente il gene causale, e non ha direzione nota. Senza tetto si
    presenta al lettore con lo stesso livello di sirolimus.
    """

    def test_direzione_ignota_non_raggiunge_il_livello_piu_alto(self):
        alto_coerente = tier_for(0.85, "coherent")
        alto_ignoto = tier_for(0.85, "unknown")
        assert alto_coerente[0] != alto_ignoto[0]
        assert alto_ignoto[1], "sotto il tetto il flag di evidenza debole resta acceso"

    def test_direzione_incoerente_e_limitata_allo_stesso_modo(self):
        assert tier_for(0.85, "incoherent")[0] == tier_for(0.85, "unknown")[0]

    def test_la_direzione_coerente_non_viene_limitata(self):
        _nome, weak = tier_for(0.85, "coherent")
        assert not weak

    def test_un_punteggio_gia_basso_non_viene_alzato_dal_tetto(self):
        # Il tetto abbassa, non promuove.
        basso = tier_for(0.05, "unknown")
        assert basso[1]
        assert basso[0] == tier_for(0.05, "coherent")[0]

    def test_senza_verdetto_il_comportamento_resta_quello_storico(self):
        assert tier_for(0.85)[0] == tier_for(0.85, "coherent")[0]
