"""Report Markdown per la revisione umana.

Il documento e' scritto per un lettore che potrebbe leggerne solo l'inizio e la
fine: per questo il disclaimer compare in entrambe le posizioni, e ogni singola
riga della tabella dei candidati porta il proprio livello di evidenza. Un
disclaimer che si puo' saltare scorrendo non e' un disclaimer.
"""

from __future__ import annotations

from ..llm.narrate import NarrationReport
from ..models import Candidate, EvidenceBundle

DISCLAIMER = """\
> [!WARNING]
> **IPOTESI DI RICERCA GENERATE AL CALCOLATORE — NON SONO CONSIGLI MEDICI.**
>
> Il contenuto di questo documento e' prodotto automaticamente incrociando basi
> di dati biomediche aperte. **Nessuna** delle ipotesi qui elencate e' stata
> verificata in vitro, in vivo o clinicamente da questo strumento.
>
> Questo non e' un dispositivo medico, non e' uno strumento diagnostico e non e'
> uno strumento prescrittivo. Non usare questo documento per prendere decisioni
> cliniche, per modificare una terapia in corso o per assumere un farmaco.
>
> La presenza di un farmaco in questo elenco **non** indica che sia efficace per
> la malattia considerata. Indica soltanto che esiste un collegamento formale fra
> il suo bersaglio molecolare e un pathway che contiene il gene causale.
>
> Destinatario previsto: un ricercatore qualificato, che valuti ogni ipotesi
> risalendo alle fonti citate.
"""

_VERDICT_BADGE = {
    "coherent": "coerente",
    "incoherent": "**INCOERENTE**",
    "unknown": "non determinabile",
}

_COMPONENT_IT = {
    "pathway_proximity": "prossimita' nel pathway",
    "pathway_specificity": "specificita' del pathway",
    "direction_coherence": "coerenza direzionale",
    "interaction_support": "supporto delle fonti",
    "literature_support": "presenza in letteratura",
    "route_directness": "direttezza del percorso",
}


def _score_table(candidate: Candidate) -> str:
    rows = ["| Componente | Valore | Peso | Contributo |", "|---|---:|---:|---:|"]
    contributions = candidate.score.contributions()
    for key, value in candidate.score.components.items():
        rows.append(
            f"| {_COMPONENT_IT.get(key, key)} | {value:.2f} | "
            f"{candidate.score.weights.get(key, 0):.2f} | {contributions.get(key, 0):.3f} |"
        )
    rows.append(f"| **Totale** | | | **{candidate.score.total:.3f}** |")
    return "\n".join(rows)


def _regulatory_lines(c: Candidate) -> list[str]:
    """Righe sulla conferma regolatoria FDA.

    Servono a rendere evidente che l'ipotesi e' fuori indicazione: vedere per
    cosa il farmaco sia realmente etichettato dice al revisore, senza doverlo
    spiegare, di che tipo di salto si sta parlando.

    L'assenza di etichetta FDA NON significa "non approvato": openFDA copre gli
    Stati Uniti, e molti farmaci per malattie rare sono autorizzati solo da EMA.
    Segnala pero' una discordanza con il flag `approved` di DGIdb, che vale la
    pena guardare: nel caso pilota Niemann-Pick, il candidato in prima posizione
    risultava approvato secondo DGIdb e privo di qualunque etichetta FDA.
    """
    reg = c.regulatory
    if reg is None:
        return []

    if not reg.label_found:
        return [
            "- **Etichetta FDA**: nessuna trovata. "
            "DGIdb lo marca approvato, ma openFDA non ha un'etichetta corrispondente. "
            "Puo' significare che l'approvazione e' extra-USA, oppure che il flag di "
            "DGIdb deriva da un'aggregazione poco affidabile: vale la pena verificarlo.",
        ]

    lines = ["- **Etichetta FDA**: presente"]
    if reg.approval_kind:
        lines[0] += f" ({reg.approval_kind})"
    if reg.routes:
        lines[0] += f", via {', '.join(r.lower() for r in reg.routes)}"
    if reg.labeled_indications:
        lines.append(
            f"- **Indicazioni etichettate** (NON questa malattia): {reg.labeled_indications}"
        )
    return lines


def _candidate_section(index: int, c: Candidate) -> str:
    flag = ""
    if c.direction.verdict == "incoherent":
        flag = (
            "\n> [!CAUTION]\n"
            "> **Direzione dell'effetto incoerente.** Secondo il meccanismo annotato, "
            "l'azione di questo farmaco andrebbe nella stessa direzione del difetto "
            "anziche' opporvisi. E' elencato per rendere visibile il conflitto, non "
            "come candidato da perseguire.\n"
        )
    elif c.weak_evidence_flag:
        flag = (
            "\n> [!NOTE]\n"
            f"> **Evidenza {c.tier}.** Il collegamento e' indiretto o poco supportato. "
            "Da trattare come spunto esplorativo, non come ipotesi consolidata.\n"
        )

    bridge = c.pathway_link.bridge
    if bridge:
        origin = bridge.source_disease_name or bridge.source_disease_id
        flag = (
            "\n> [!IMPORTANT]\n"
            "> **Candidato indiretto: ponte fenotipico.** Questo farmaco non e' stato "
            "raggiunto dal gene causale della malattia interrogata, ma da "
            f"`{bridge.borrowed_gene}`, gene causale di *{origin}*, che condivide "
            f"fenotipi con somiglianza {bridge.similarity:.2f}. Che due malattie si "
            "somiglino clinicamente non implica che condividano un meccanismo: "
            "l'ipotesi e' piu' indiretta di quanto il punteggio da solo suggerisca.\n"
        ) + flag

    lines = [
        f"### {index}. {c.drug_name}",
        "",
        f"- **Bersaglio molecolare**: {c.target_gene}",
        f"- **Distanza dal gene causale**: {c.pathway_link.hops} hop",
        f"- **Pathway usato per lo score**: {c.pathway_link.pathway.name} "
        f"(`{c.pathway_link.pathway.reactome_id}`, {c.pathway_link.pathway.size} geni)",
    ]

    if bridge:
        shared = "; ".join(bridge.shared_phenotypes[:6]) or "—"
        lines += [
            f"- **Percorso**: ponte fenotipico via `{bridge.borrowed_gene}` "
            f"({bridge.source_disease_name or bridge.source_disease_id}, "
            f"`{bridge.source_disease_id}`)",
            f"- **Somiglianza fenotipica**: {bridge.similarity:.3f}",
            f"- **Fenotipi condivisi**: {shared}",
        ]
    else:
        lines.append("- **Percorso**: diretto dal gene causale della malattia interrogata")

    others = [p for p in c.pathway_link.shared_pathways if p != c.pathway_link.pathway.name]
    if others:
        listed = "; ".join(others[:6])
        more = f" (e altri {len(others) - 6})" if len(others) > 6 else ""
        lines.append(f"- **Altri pathway condivisi**: {listed}{more}")

    lines += [
        "- **Coerenza direzionale**: "
        + _VERDICT_BADGE.get(c.direction.verdict, c.direction.verdict),
        f"- **Tipo di interazione (DGIdb)**: "
        f"{', '.join(c.interaction.interaction_types) or 'non specificato'}",
        f"- **Fonti a monte dell'interazione**: "
        f"{', '.join(c.interaction.source_dbs) or 'nessuna registrata'}",
        f"- **Livello di evidenza**: **{c.tier}** (punteggio {c.score.total:.3f})",
        *_regulatory_lines(c),
        flag,
        "",
        "**Meccanismo ipotizzato**",
        "",
        c.narrative or "_(nessuna spiegazione generata)_",
        "",
        "<details><summary>Scomposizione del punteggio</summary>",
        "",
        _score_table(c),
        "",
        "</details>",
        "",
    ]

    if c.literature:
        lines.append("**Letteratura (solo conteggi e identificativi reali)**")
        lines.append("")
        for lit in c.literature:
            lines.append(f"- `{lit.query_string}` → **{lit.total_count}** risultati su PubMed")
            for art in lit.articles[:3]:
                year = f", {art.year}" if art.year else ""
                journal = f", _{art.journal}_" if art.journal else ""
                lines.append(
                    f"  - [PMID:{art.pmid}]({art.url}) — "
                    f"{art.title or '(senza titolo)'}{journal}{year}"
                )
        lines.append("")

    return "\n".join(lines)


def render_report(bundle: EvidenceBundle, narration: NarrationReport | None = None) -> str:
    d = bundle.disease
    causal = ", ".join(f"`{cg.gene.symbol}`" for cg in bundle.causal_genes)

    parts: list[str] = [
        f"# Ipotesi di riposizionamento terapeutico — {d.label}",
        "",
        DISCLAIMER,
        "",
        "## Query",
        "",
        f"- **Malattia**: {d.label} (`{d.mondo_id}`)",
    ]
    if d.orpha_codes:
        parts.append(f"- **Orphanet**: {', '.join(f'`{o}`' for o in d.orpha_codes)}")
    if d.omim_ids:
        parts.append(f"- **OMIM**: {', '.join(f'`{o}`' for o in d.omim_ids)}")
    parts += [
        f"- **Geni causali** (associazioni curate Orphanet): {causal or '_nessuno_'}",
        f"- **Meccanismo annotato**: `{bundle.mechanism.value}`",
    ]
    if bundle.mechanism_rationale:
        parts.append(f"- **Motivazione del meccanismo**: {bundle.mechanism_rationale.strip()}")
    parts += [
        f"- **Generato il**: {bundle.generated_at:%Y-%m-%d %H:%M}",
        f"- **Impronta della configurazione**: `{bundle.config_digest}` "
        "(due report con impronta diversa non sono confrontabili)",
        "",
    ]

    if narration:
        parts += ["> **Provenienza del testo.** " + narration.note(), ""]

    if bundle.literature_shortlist_truncated:
        parts += [
            "> [!WARNING]",
            "> **Selezione troncata.** Il tetto sul numero di candidati per cui "
            "interrogare PubMed ha tagliato: alcuni candidati non sono stati "
            "interrogati e possono mancare da questo elenco. Un'assenza non e' "
            "quindi necessariamente un giudizio del metodo.",
            "",
        ]

    # --- tabella di sintesi
    parts += [
        "## Candidati",
        "",
        f"{len(bundle.candidates)} candidati sopra la soglia di punteggio, "
        "ordinati per punteggio decrescente.",
        "",
        "| # | Farmaco | Bersaglio | Hop | Percorso | Direzione | Punteggio | Evidenza |",
        "|---:|---|---|---:|---|---|---:|---|",
    ]
    for i, c in enumerate(bundle.candidates, 1):
        parts.append(
            f"| {i} | {c.drug_name} | `{c.target_gene}` | {c.pathway_link.hops} | "
            f"{'ponte' if c.pathway_link.bridge else 'diretto'} | "
            f"{_VERDICT_BADGE.get(c.direction.verdict, c.direction.verdict)} | "
            f"{c.score.total:.3f} | {c.tier} |"
        )
    parts.append("")

    if not bundle.candidates:
        parts += [
            "_Nessun candidato ha superato la soglia. Un risultato vuoto e' un esito "
            "legittimo: significa che con le fonti e i filtri correnti non esiste un "
            "collegamento sufficientemente specifico._",
            "",
        ]

    # --- dettaglio
    parts.append("## Dettaglio dei candidati")
    parts.append("")
    for i, c in enumerate(bundle.candidates, 1):
        parts.append(_candidate_section(i, c))

    # --- provenienza
    parts += [
        "## Fonti dei dati",
        "",
        "| Fonte | Licenza | Versione | Accesso |",
        "|---|---|---|---|",
    ]
    for p in sorted(bundle.provenances, key=lambda x: x.source_name):
        parts.append(
            f"| {p.source_name} | {p.license} | {p.version or '—'} | "
            f"{p.accessed_at.isoformat() if p.accessed_at else '—'} |"
        )
    parts += [
        "",
        "I dati non sono ridistribuiti da questo strumento: sono stati scaricati in "
        "locale dalle fonti originali e restano soggetti alle rispettive licenze.",
        "",
        "## Come leggere questo documento",
        "",
        "- **Hop** e' la distanza fra il gene causale e il bersaglio del farmaco: "
        "`0` significa stesso gene, `1` stesso pathway, `2` pathway adiacente. "
        "Piu' e' alto, piu' il collegamento e' indiretto.",
        "- **Direzione** dice se l'azione del farmaco si oppone al difetto. "
        "`non determinabile` non e' rassicurante: significa che non e' noto se il "
        "farmaco correggerebbe o aggraverebbe il problema.",
        "- Il **punteggio** e' una somma pesata di componenti dichiarate in "
        "`config/scoring.yaml`, non la stima di una probabilita' di successo. "
        "Serve a ordinare, non a quantificare.",
        "- Il **percorso** dice da dove arriva il candidato. `diretto` significa dal gene "
        "causale della malattia interrogata; `ponte fenotipico` significa dal gene causale "
        "di un'altra malattia clinicamente somigliante, ed e' un'ipotesi sensibilmente piu' "
        "indiretta, gia' penalizzata nel punteggio dalla componente di direttezza.",
        "- L'**etichetta FDA** serve a rendere visibile che l'ipotesi e' fuori "
        "indicazione: mostra per cosa il farmaco sia realmente autorizzato. La sua "
        'assenza non significa "non approvato", perche\' openFDA copre solo gli Stati '
        "Uniti, ma segnala una discordanza con DGIdb che vale la pena verificare.",
        "- Il **conteggio di letteratura** misura quanta attenzione ha ricevuto un "
        "accostamento, non se funziona: un accostamento molto studiato puo' esserlo "
        "perche' e' stato ripetutamente smentito.",
        "",
        "---",
        "",
        DISCLAIMER,
    ]

    return "\n".join(parts)
