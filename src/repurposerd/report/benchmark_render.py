"""Report del banco di prova.

Il documento e' pensato per essere confrontato con un altro documento uguale
prodotto da una configurazione diversa: per questo l'impronta di configurazione
e i parametri di esecuzione compaiono in testa, e i numeri aggregati vengono
prima del dettaglio.
"""

from __future__ import annotations

from ..benchmark import BenchmarkReport, CaseResult

_KIND_IT = {
    "repurposing": "riposizionamento",
    "on_label": "in indicazione",
    "structural_miss": "fallimento atteso",
}


def _esito(r: CaseResult) -> str:
    if r.error:
        return "ERRORE"
    if r.kind == "structural_miss":
        return "correttamente non trovato" if not r.found else "**TROVATO (inatteso)**"
    if not r.found:
        return "**non trovato**"
    return f"#{r.rank}"


def render_benchmark(report: BenchmarkReport) -> str:
    parts: list[str] = [
        "# Banco di prova — copertura sui riposizionamenti noti",
        "",
        "> [!NOTE]",
        "> Questo documento misura la **copertura**: se il farmaco atteso compaia "
        "fra i candidati e in che posizione. **Non misura la precisione.** Un "
        "candidato non atteso non e' un falso positivo: potrebbe essere "
        "un'ipotesi legittima che nessuno ha ancora studiato. Leggerlo come una "
        "misura di correttezza complessiva sarebbe un errore.",
        "",
        "## Configurazione",
        "",
        f"- **Impronta**: `{report.config_digest}` — confrontabile solo con report "
        "che riportano la stessa impronta",
        f"- **Candidati esaminati per caso**: {report.top_n}",
        f"- **Letteratura**: {'interrogata' if report.with_literature else 'saltata'}",
        f"- **Ponte fenotipico**: {'attivo' if report.with_phenotype_bridge else 'disattivo'}",
        f"- **Eseguito il**: {report.generated_at:%Y-%m-%d %H:%M}",
        "",
        "## Risultati aggregati",
        "",
    ]

    trovabili = report._of_kind("repurposing", "on_label")
    parts += [
        "Sui casi che **devono** essere trovati (riposizionamenti e farmaci in indicazione):",
        "",
        "| Metrica | Valore |",
        "|---|---|",
    ]
    for k in (5, 10, 20, 40):
        if k <= report.top_n:
            hit, tot = report.recall_at(k)
            pct = f"{100 * hit / tot:.0f}%" if tot else "—"
            parts.append(f"| Trovati entro la posizione {k} | {hit}/{tot} ({pct}) |")

    mediana = report.median_rank()
    parts.append(
        f"| Posizione mediana dei trovati | {mediana:.0f} |"
        if mediana
        else "| Posizione mediana | — |"
    )
    non_trovati = [r for r in trovabili if not r.found and not r.error]
    parts.append(f"| Mai trovati | {len(non_trovati)}/{len(trovabili)} |")

    # Distinzione fra i due gruppi: mescolarli nasconderebbe che il ramo
    # meccanicistico e' molto piu' facile del riposizionamento vero.
    parts += [
        "",
        "Scomposto per tipo di caso:",
        "",
        "| Tipo | Trovati entro 40 | Mediana |",
        "|---|---|---|",
    ]
    for kind in ("repurposing", "on_label"):
        hit, tot = report.recall_at(report.top_n, kind)
        med = report.median_rank(kind)
        parts.append(f"| {_KIND_IT[kind]} | {hit}/{tot} | {f'{med:.0f}' if med else '—'} |")

    strutturali = report._of_kind("structural_miss")
    if strutturali:
        corretti = sum(1 for r in strutturali if not r.found)
        parts += [
            "",
            f"**Fallimenti attesi**: {corretti}/{len(strutturali)} correttamente non trovati. "
            "Se questo numero scendesse, lo strumento starebbe diventando promiscuo: "
            "alzerebbe la copertura restituendo tutto.",
        ]

    tagliati = report.truncated()
    if tagliati:
        mancanti = [r for r in tagliati if not r.found and r.kind != "structural_miss"]
        parts += [
            "",
            "> [!WARNING]",
            f"> **{len(tagliati)} casi hanno superato il tetto della preselezione** "
            "per la letteratura. In quei casi la garanzia del criterio di selezione "
            "non vale, e un farmaco atteso assente puo' non essere stato interrogato "
            "affatto. "
            + (
                f"Riguarda {len(mancanti)} dei non trovati: "
                + ", ".join(f"`{r.case_id}`" for r in mancanti)
                if mancanti
                else "Nessuno dei non trovati e' fra questi."
            ),
        ]

    errori = report.errors()
    if errori:
        parts += [
            "",
            "> [!WARNING]",
            f"> **{len(errori)} casi non eseguiti** per errore di risoluzione. "
            "Non contano ne' come successo ne' come fallimento del metodo, ma "
            "vanno corretti perche' riducono la dimensione effettiva del banco.",
        ]

    # --- dettaglio
    parts += [
        "",
        "## Dettaglio",
        "",
        "| Caso | Malattia | Farmaco atteso | Tipo | Esito | Punteggio | Percorso |",
        "|---|---|---|---|---|---:|---|",
    ]
    for r in report.results:
        percorso = "—"
        if r.found:
            percorso = "ponte" if r.via_bridge else "diretto"
            if r.target_gene:
                percorso += f" ({r.target_gene})"
        parts.append(
            f"| `{r.case_id}` | {r.disease} | {r.expected_drug} | {_KIND_IT.get(r.kind, r.kind)} | "
            f"{_esito(r)} | {f'{r.score:.3f}' if r.score is not None else '—'} | {percorso} |"
        )

    if errori:
        parts += ["", "### Casi non eseguiti", ""]
        for r in errori:
            parts.append(f"- `{r.case_id}` ({r.disease}): {r.error}")

    parts += [
        "",
        "## Come usare questi numeri",
        "",
        "- **Per confrontare configurazioni**: eseguire il banco prima e dopo una "
        "modifica ai pesi e confrontare la copertura e la posizione mediana. Due "
        "report con impronta di configurazione diversa non sono confrontabili "
        "sui punteggi assoluti, ma lo sono sugli ordinamenti.",
        "- **Non per dichiarare che lo strumento funziona.** Ventidue casi sono "
        "pochi, e sono tutti riposizionamenti gia' noti e quindi gia' studiati, "
        "con letteratura abbondante. Il comportamento su un accostamento che "
        "nessuno ha ancora esaminato non e' misurato qui e non e' misurabile "
        "con un banco costruito sui casi riusciti.",
        "- **Attenzione alla circolarita'.** La componente di letteratura premia "
        "gli accostamenti gia' studiati, e tutti i casi di questo banco lo sono. "
        "La copertura misurata e' quindi una stima ottimistica.",
        "",
    ]
    return "\n".join(parts)
