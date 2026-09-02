"""Generazione delle spiegazioni, con validazione obbligatoria.

Il ciclo e' deliberatamente severo: genera, valida, e se la validazione fallisce
riprova una volta sola; al secondo fallimento ripiega sul testo deterministico.
Non si tenta di "riparare" il testo generato, perche' correggere un output che
ha gia' inventato qualcosa significa fidarsi del resto di quello stesso output.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from rich.console import Console

from ..models import Candidate, EvidenceBundle
from .backend import LLMBackend, LLMUnavailable, TemplateBackend
from .prompts import SYSTEM_PROMPT, build_prompt, render_template
from .validator import ValidationResult, validate

console = Console()

MAX_ATTEMPTS = 2


@dataclass
class NarrationReport:
    """Statistiche del passaggio di generazione, riportate nel report finale.

    Il numero di ripieghi non e' un dettaglio implementativo: dice al lettore
    quanto del documento e' stato scritto da un modello e quanto da un template,
    e quante volte il modello ha provato ad affermare qualcosa di non supportato.
    """

    backend: str
    generated: int = 0
    fallback: int = 0
    rejected: int = 0
    # Testo deterministico per scelta dell'utente (oltre `--narrate-top`), non
    # per un fallimento. Le due cose vanno contate separatamente: confonderle
    # farebbe sembrare un limite imposto un problema del modello, o viceversa.
    templated_by_design: int = 0
    violations: list[str] = field(default_factory=list)

    def note(self) -> str:
        if self.backend == "template":
            total = self.fallback + self.templated_by_design
            return (
                f"Tutte le {total} spiegazioni sono state costruite dal generatore "
                "deterministico: nessun modello linguistico e' intervenuto."
            )
        parts = [
            f"Backend: {self.backend}. {self.generated} spiegazioni generate e validate",
        ]
        if self.rejected:
            parts.append(
                f"{self.rejected} generazioni respinte dal validatore "
                f"(motivi: {'; '.join(self.violations[:5])})"
            )
        if self.fallback:
            parts.append(f"{self.fallback} ripieghi sul testo deterministico")
        if self.templated_by_design:
            parts.append(
                f"{self.templated_by_design} spiegazioni costruite dal generatore "
                "deterministico per scelta (oltre il limite di narrazione richiesto), "
                "non per un fallimento del modello"
            )
        return ". ".join(parts) + "."


def narrate_bundle(
    bundle: EvidenceBundle,
    backend: LLMBackend,
    known_genes: set[str] | None = None,
    known_drugs: set[str] | None = None,
    narrate_top: int | None = None,
) -> NarrationReport:
    """Popola `candidate.narrative` per ogni candidato del bundle.

    `narrate_top` limita la generazione ai primi N candidati; per i restanti si
    usa il generatore deterministico.

    PERCHE' SERVE
    Non e' un risparmio qualsiasi: e' cio' che rende praticabile un modello
    grande. Un report da quaranta candidati con un modello da sette miliardi di
    parametri su CPU richiede circa sei ore e mezza, e nessuno lo eseguira'.
    Narrare i primi cinque e lasciare il resto al generatore deterministico
    porta lo stesso report a meno di un'ora, senza perdere nulla di verificabile:
    il testo deterministico ricopia gli stessi campi strutturati, e il report
    dichiara candidato per candidato da dove viene la prosa.

    L'ordine dei candidati e' gia' quello finale, quindi i primi N sono i piu'
    alti in classifica: sono quelli che un revisore leggera' per esteso.
    """
    report = NarrationReport(backend=backend.describe())

    if isinstance(backend, TemplateBackend):
        # Scelta esplicita dell'utente, non un fallimento: va contata a parte.
        for c in bundle.candidates:
            c.narrative = render_template(c, bundle)
            report.templated_by_design += 1
        return report

    if not backend.available():
        console.print(
            f"  [yellow]{backend.describe()} non raggiungibile: "
            "si usa il generatore deterministico.[/yellow]"
        )
        report.backend = "template (ripiego: backend non disponibile)"
        for c in bundle.candidates:
            c.narrative = render_template(c, bundle)
            report.fallback += 1
        return report

    total = len(bundle.candidates)
    limit = total if narrate_top is None else max(0, narrate_top)
    if limit < total:
        console.print(
            f"  [dim]generazione limitata ai primi {limit} candidati; "
            f"per i restanti {total - limit} si usa il generatore deterministico[/dim]"
        )

    for i, c in enumerate(bundle.candidates, 1):
        if i > limit:
            c.narrative = render_template(c, bundle)
            report.templated_by_design += 1
            continue

        # Su CPU senza accelerazione una singola generazione puo' richiedere
        # minuti: senza questa riga l'utente non distingue "lento" da "bloccato".
        console.print(f"  [dim]({i}/{limit})[/dim] {c.drug_name} ...")
        started = time.monotonic()
        text, _result, rejections, reasons = _generate_validated(
            c, bundle, backend, known_genes, known_drugs
        )
        elapsed = time.monotonic() - started
        report.rejected += rejections
        # Le violazioni si ripetono spesso fra un tentativo e l'altro: elencarle
        # una sola volta rende la nota leggibile senza perdere informazione.
        for reason in reasons:
            if reason not in report.violations:
                report.violations.append(reason)
        if text is None:
            c.narrative = render_template(c, bundle)
            report.fallback += 1
            console.print(
                f"      [yellow]ripiego sul testo deterministico[/yellow] ({elapsed:.0f}s)"
            )
        else:
            c.narrative = text
            report.generated += 1
            console.print(f"      [green]generato e validato[/green] ({elapsed:.0f}s)")
    return report


def _generate_validated(
    candidate: Candidate,
    bundle: EvidenceBundle,
    backend: LLMBackend,
    known_genes: set[str] | None,
    known_drugs: set[str] | None,
) -> tuple[str | None, ValidationResult | None, int, list[str]]:
    """Ritorna (testo, ultimo esito, numero di respingimenti, motivi).

    Il numero di respingimenti conta le GENERAZIONI respinte, non le violazioni:
    un singolo testo puo' violare piu' regole insieme, e contarle una per una
    farebbe sembrare che il modello abbia sbagliato piu' volte di quante ne abbia
    avute occasione.

    I motivi si accumulano anche quando un tentativo successivo riesce. Altrimenti
    il report direbbe "1 generazione respinta (motivi: )", cioe' dichiarerebbe un
    respingimento senza dire quale: il conteggio serve proprio a far sapere al
    lettore che cosa il modello ha provato ad affermare.
    """
    prompt = build_prompt(candidate, bundle)
    last: ValidationResult | None = None
    rejections = 0
    rejection_reasons: list[str] = []

    for attempt in range(MAX_ATTEMPTS):
        try:
            text = backend.generate(SYSTEM_PROMPT, prompt)
        except LLMUnavailable as exc:
            console.print(f"      [yellow]generazione fallita: {exc}[/yellow]")
            return None, last, rejections, rejection_reasons

        if not text.strip():
            continue

        last = validate(
            text,
            bundle,
            drug_name=candidate.drug_name,
            known_genes=known_genes,
            known_drugs=known_drugs,
            # Il prompt e' esattamente cio' che il modello ha visto: usarlo come
            # vocabolario rende vera per costruzione l'invariante "puo' citare
            # solo cio' che gli e' stato mostrato".
            shown_context=prompt,
        )
        if last.ok:
            return text.strip(), last, rejections, rejection_reasons

        rejections += 1
        rejection_reasons.extend(str(v) for v in last.violations)
        console.print(
            f"      [yellow]validazione respinta[/yellow] (tentativo {attempt + 1}): "
            f"{last.summary()}"
        )

    return None, last, rejections, rejection_reasons
