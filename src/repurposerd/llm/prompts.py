"""Prompt e testo deterministico di ripiego.

Le regole 3 e 4 del prompt di sistema elencano parole vietate una per una, il
che sembra pedante finche' non si guardano i dati: `qwen2.5:7b` ha scritto «il
meccanismo ipotizzato per l'efficacia del sirolimus» pur avendo l'istruzione di
non affermare efficacia. Non stava affermando nulla — stava presupponendo, e
un divieto formulato come "non affermare" non copre il presupposto.

Il prompt deve elencare le stesse radici che il validatore rifiuta. Se le due
liste divergono, il modello viene respinto per una regola che non gli e' stata
data, e ogni generazione finisce nel ripiego deterministico.

Il prompt e' costruito in modo che il modello non abbia nulla da recuperare: il
suo unico compito e' riformulare in italiano leggibile un insieme di fatti che
gli vengono consegnati per intero. Ogni istruzione qui dentro esiste per
restringere lo spazio di cio' che il modello puo' dire, non per allargarlo.
"""

from __future__ import annotations

import json

from ..models import Candidate, EvidenceBundle

SYSTEM_PROMPT = """\
Sei un assistente che redige note metodologiche per ricercatori biomedici.

Ricevi un insieme di FATTI VERIFICATI su una possibile ipotesi di riposizionamento
terapeutico. Il tuo compito e' riformularli in italiano chiaro e sobrio.

REGOLE INDEROGABILI

1. Non aggiungere NESSUNA informazione che non sia nei fatti forniti.
   Non hai accesso a fonti esterne. Se un dato non c'e', non esiste.
2. Non citare MAI un PMID, un identificatore, un gene o un farmaco che non
   compaia nei fatti forniti. Inventare una citazione e' l'errore piu' grave
   possibile in questo contesto.
3. NON usare MAI le parole "efficacia" ed "efficace", in nessuna forma e in
   nessun contesto, nemmeno per negarle o per dire che andrebbero studiate.
   Scrivi invece di "effetto atteso", "plausibilita' del meccanismo",
   "verifica sperimentale". Non affermare che un farmaco sia curativo,
   raccomandato o clinicamente validato: si tratta di un'ipotesi generata al
   calcolatore e mai verificata sperimentalmente.
4. Parla della valutazione direzionale come di una VALUTAZIONE, non di un
   risultato accertato: scrivi "risulta compatibile", "sarebbe compatibile",
   "la valutazione euristica indica". Le interazioni farmaco-gene puoi dirle
   "riportate" o "documentate" da N database, perche' e' un'affermazione sui
   dati. Non attribuire a ipotesi, meccanismo, coerenza o direzione gli
   aggettivi "confermato", "dimostrato", "provato", "affidabile", ne' definire
   qualcosa "altamente probabile".
5. Non fornire indicazioni di dosaggio, posologia o somministrazione.
6. Usa il condizionale per il meccanismo ipotizzato ("potrebbe", "sarebbe
   atteso"). Usa l'indicativo solo per i fatti riportati nelle fonti.
7. Se la coerenza direzionale e' 'unknown' o 'incoherent', dillo esplicitamente
   e spiega cosa manca. Non minimizzarlo.
8. Se 'ponte_fenotipico' non e' nullo, il candidato NON deriva dal gene causale
   della malattia interrogata ma da quello di una malattia clinicamente simile.
   Dillo apertamente: e' un'ipotesi piu' indiretta, e la somiglianza fra sintomi
   non dimostra che le due malattie condividano un meccanismo.

FORMATO
Da tre a cinque frasi in un unico paragrafo. Nessun elenco puntato, nessun
titolo, nessuna intestazione. Scrivi solo il paragrafo.
"""

# Le etichette portano con se' il proprio limite.
#
# PERCHE'
# Il campo si chiamava `esito` e valeva `coerente`. Un modello che legge
# «esito: coerente» scrive naturalmente «la coerenza del meccanismo e'
# confermata» — che e' una sovradichiarazione, perche' la coerenza qui e' il
# risultato di un'euristica e nulla la conferma. Misurato su qwen2.5:7b: quella
# frase esatta ha causato quattro respingimenti su cinque generazioni.
#
# Vietare la parola non bastava: il modello continuava a produrla perche' il
# campo la suggeriva. Formulare il fatto in modo che porti gia' la sua riserva
# e' piu' efficace di qualunque divieto, e non e' un trucco di prompting: e'
# rendere il dato piu' onesto anche verso chi lo legge nel bundle JSON.
_VERDICT_IT = {
    "coherent": "compatibile secondo la valutazione euristica, mai verificata sperimentalmente",
    "incoherent": "INCOMPATIBILE secondo la valutazione euristica",
    "unknown": "non determinabile con i dati disponibili",
}


def candidate_facts(candidate: Candidate, bundle: EvidenceBundle) -> dict:
    """I fatti, e solo i fatti, che il modello e' autorizzato a usare."""
    return {
        "malattia": {
            "nome": bundle.disease.label,
            "identificatore": bundle.disease.mondo_id,
            "meccanismo": bundle.mechanism.value,
        },
        "geni_causali": [cg.gene.symbol for cg in bundle.causal_genes],
        "farmaco_candidato": candidate.drug_name,
        "bersaglio_del_farmaco": candidate.target_gene,
        "collegamento_pathway": {
            "distanza_hop": candidate.pathway_link.hops,
            "pathway_principale": candidate.pathway_link.pathway.name,
            "geni_nel_pathway": candidate.pathway_link.pathway.size,
            "tutti_i_pathway_condivisi": candidate.pathway_link.shared_pathways,
            "percorso": candidate.pathway_link.route,
        },
        # Presente solo per i candidati del ramo fenotipico. La sua assenza
        # significa che il candidato deriva dal gene causale della malattia
        # interrogata, non da quello di una malattia somigliante.
        "ponte_fenotipico": (
            {
                "malattia_di_origine": candidate.pathway_link.bridge.source_disease_name,
                "identificatore": candidate.pathway_link.bridge.source_disease_id,
                "somiglianza_fenotipica": candidate.pathway_link.bridge.similarity,
                "gene_preso_in_prestito": candidate.pathway_link.bridge.borrowed_gene,
                "fenotipi_condivisi": candidate.pathway_link.bridge.shared_phenotypes[:6],
            }
            if candidate.pathway_link.bridge
            else None
        ),
        "interazione_farmaco_gene": {
            "tipi": candidate.interaction.interaction_types,
            "database_a_monte": candidate.interaction.source_dbs,
            "approvato": candidate.interaction.approved,
        },
        "coerenza_direzionale": {
            "valutazione_euristica": _VERDICT_IT.get(
                candidate.direction.verdict, candidate.direction.verdict
            ),
            "stato_atteso_del_bersaglio": candidate.direction.expected_target_state,
            "azione_del_farmaco": candidate.direction.drug_action,
            "motivazione": candidate.direction.rationale,
        },
        "letteratura": [
            {
                "interrogazione": lit.query_label,
                "articoli_trovati": lit.total_count,
                "pmid_esempio": [a.pmid for a in lit.articles],
            }
            for lit in candidate.literature
        ],
        "etichetta_fda": (
            {
                "trovata": candidate.regulatory.label_found,
                "indicazioni_etichettate_per_ALTRE_malattie": (
                    candidate.regulatory.labeled_indications
                ),
            }
            if candidate.regulatory
            else None
        ),
        "punteggio": {
            "totale": candidate.score.total,
            "livello_di_evidenza": candidate.tier,
            "componenti": candidate.score.components,
        },
    }


def build_prompt(candidate: Candidate, bundle: EvidenceBundle) -> str:
    facts = json.dumps(candidate_facts(candidate, bundle), ensure_ascii=False, indent=2)
    return (
        "FATTI VERIFICATI (usa esclusivamente questi):\n\n"
        f"{facts}\n\n"
        f"Scrivi il paragrafo che descrive il meccanismo ipotizzato per "
        f"{candidate.drug_name} in relazione a {bundle.disease.label}, e il grado di "
        f"fiducia che l'evidenza raccolta consente."
    )


# --------------------------------------------------------------------------
# Ripiego deterministico


_STATE_IT = {"hyperactive": "iperattivo", "hypoactive": "ipoattivo", "unknown": "indeterminato"}


def render_template(candidate: Candidate, bundle: EvidenceBundle) -> str:
    """Prosa costruita meccanicamente dai campi del candidato.

    Usata quando non c'e' un modello locale, o quando il testo generato non
    supera la validazione. Non e' una versione degradata: e' l'unica variante di
    cui si puo' dimostrare che non contiene nulla di inventato, perche' non
    genera niente, ricopia.
    """
    link = candidate.pathway_link
    d = candidate.direction
    causal = ", ".join(cg.gene.symbol for cg in bundle.causal_genes)

    bridge_note = ""
    if link.bridge:
        shared = ", ".join(link.bridge.shared_phenotypes[:3])
        bridge_note = (
            f" Attenzione: questo candidato non deriva dal gene causale di "
            f"{bundle.disease.label}, ma da {link.bridge.borrowed_gene}, gene causale di "
            f"{link.bridge.source_disease_name or link.bridge.source_disease_id}, malattia "
            f"con somiglianza fenotipica {link.bridge.similarity:.2f} "
            f"(fenotipi condivisi: {shared}). La somiglianza clinica non dimostra un "
            f"meccanismo condiviso, quindi l'ipotesi e' piu' indiretta."
        )

    if link.hops == 0:
        bridge = (
            f"{candidate.drug_name} agisce direttamente su {candidate.target_gene}, "
            f"che e' il gene causale della malattia."
        )
    elif link.hops == 1:
        bridge = (
            f"{candidate.drug_name} agisce su {candidate.target_gene}, annotato insieme a "
            f"{link.causal_gene} nel pathway Reactome «{link.pathway.name}» "
            f"({link.pathway.size} geni)."
        )
    else:
        bridge = (
            f"{candidate.drug_name} agisce su {candidate.target_gene}, che appartiene a "
            f"«{link.pathway.name}», pathway adiacente nella gerarchia Reactome a quelli "
            f"che contengono {link.causal_gene}."
        )

    if d.verdict == "coherent":
        direction = (
            f"La direzione dell'effetto risulta coerente: {d.rationale} "
            "Resta un'ipotesi meccanicistica, non una verifica sperimentale."
        )
    elif d.verdict == "incoherent":
        direction = (
            f"ATTENZIONE — la direzione dell'effetto risulta incoerente. {d.rationale} "
            "Il candidato e' riportato proprio per rendere visibile questo conflitto."
        )
    else:
        direction = (
            f"La direzione dell'effetto non e' determinabile. {d.rationale} "
            f"Il bersaglio sarebbe atteso "
            f"{_STATE_IT.get(d.expected_target_state, 'indeterminato')}, "
            "ma senza una relazione con segno documentata non e' possibile dire se il "
            "farmaco correggerebbe o aggraverebbe il difetto."
        )

    dbs = ", ".join(candidate.interaction.source_dbs) or "nessuna fonte a monte registrata"
    types = ", ".join(candidate.interaction.interaction_types) or "tipo non specificato"
    support = (
        f"L'interazione farmaco-gene e' riportata da: {dbs} (tipo: {types}). "
        f"Il gene causale della malattia e' {causal}."
    )

    total_lit = sum(lit.total_count for lit in candidate.literature)
    if candidate.literature:
        literature = (
            f"Su PubMed risultano {total_lit} articoli corrispondenti alle interrogazioni "
            f"effettuate; il conteggio misura quanta attenzione ha ricevuto questo "
            f"accostamento, non se funzioni."
        )
    else:
        literature = "Non e' stata interrogata la letteratura per questo candidato."

    tier = (
        f"Livello di evidenza complessivo: {candidate.tier} "
        f"(punteggio {candidate.score.total:.2f})."
    )

    return " ".join([bridge, bridge_note, direction, support, literature, tier]).replace("  ", " ")
