"""Validatore anti-allucinazione.

L'IDEA
Il modello linguistico riceve un evidence bundle e nient'altro. Dopo la
generazione, questo modulo estrae dal testo prodotto ogni identificatore, PMID,
gene e farmaco, e verifica che compaia nel bundle. Una citazione inventata non
e' quindi un rischio da mitigare con il prompting: e' una condizione
rilevabile, che fa fallire la generazione e attivare il fallback deterministico.

PERCHE' SERVONO I VOCABOLARI
Riconoscere "MTOR" come simbolo genico richiede di sapere quali stringhe sono
simboli genici. Il validatore accetta quindi i vocabolari completi di HGNC e
DGIdb: cosi' puo' distinguere "un gene che non e' nel bundle" (violazione) da
"una parola in maiuscolo qualsiasi" (innocua). Senza i vocabolari il controllo
degrada a soli identificatori e PMID, e lo dichiara.

LINGUAGGIO VIETATO
Il secondo controllo e' lessicale. Un'ipotesi computazionale descritta con le
parole dell'efficacia clinica diventa, per il lettore, un'affermazione di
efficacia clinica. Le espressioni vietate sono bloccate a prescindere dal
contesto: il costo di un falso positivo e' un ripiego sul testo deterministico,
il costo di un falso negativo e' un documento che afferma cio' che non puo'.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import EvidenceBundle

# --- Estrattori -------------------------------------------------------------

PMID_RE = re.compile(r"\bPMID:?\s*(\d{4,9})\b", re.IGNORECASE)
BARE_PMID_RE = re.compile(r"\b(\d{8})\b")
IDENTIFIER_RE = re.compile(
    r"\b(MONDO:\d+|ORPHA(?:NET)?:\d+|OMIM:\d+|R-HSA-\d+|CHEMBL\d+|HGNC:\d+|ncit:C\d+)\b",
    re.IGNORECASE,
)
# Candidati a simbolo genico: maiuscole e cifre, 3-10 caratteri.
#
# PERCHE' TRE E NON DUE
# HGNC contiene 31 simboli approvati lunghi due caratteri, fra cui SI
# (sucrasi-isomaltasi), AR, TF, TG, HP, CP. In un testo italiano "SI" e' una
# parola comunissima, e le altre sono sigle plausibili. Riconoscerle come geni
# produrrebbe falsi positivi che spingono al ripiego generazioni corrette.
#
# Il compromesso e' esplicito: si rinuncia a rilevare l'allucinazione di 31
# simboli su 45.045 (lo 0,07%), e in cambio non si respingono testi validi.
# Un modello che inventa un gene inventa quasi sempre un simbolo di lunghezza
# ordinaria, perche' e' quello che i simboli genici sembrano.
GENE_TOKEN_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,9})\b")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]+")

# Lunghezza minima di un nome di farmaco perche' valga la pena controllarlo.
MIN_DRUG_TOKEN_LENGTH = 5

# Nomi presenti in DGIdb che sono anche sostantivi comuni. Verificarli
# produrrebbe falsi positivi su prosa ordinaria senza guadagno reale: nessun
# modello "allucina" una citazione scrivendo la parola "light".
GENERIC_DRUG_NAMES = {
    "light",
    "water",
    "oxygen",
    "carbon",
    "nitrogen",
    "calcium",
    "sodium",
    "glucose",
    "alcohol",
    "ethanol",
}

# Espressioni che affermano efficacia clinica o valore terapeutico dimostrato.
FORBIDDEN_PHRASES = [
    # italiano
    "efficacia dimostrata",
    "efficacia clinica",
    "clinicamente efficace",
    "clinicamente validato",
    "clinicamente provato",
    "sicuro ed efficace",
    "e' efficace",
    "è efficace",
    "risulta efficace",
    "si e' dimostrato efficace",
    "si è dimostrato efficace",
    "cura la malattia",
    "guarisce",
    "guarigione",
    "terapia raccomandata",
    "trattamento raccomandato",
    "si raccomanda di",
    "dovrebbe essere somministrato",
    "posologia",
    "dosaggio consigliato",
    "prescrivere",
    "prescrizione",
    # inglese
    "proven effective",
    "clinically proven",
    "clinically validated",
    "safe and effective",
    "is effective",
    "cures",
    "recommended treatment",
    "should be administered",
    "recommended dose",
]

# Espressioni che presentano un'ipotesi come un fatto stabilito.
OVERCLAIM_PHRASES = [
    "e' certo che",
    "è certo che",
    "senza dubbio",
    "sicuramente",
]

# Le forme flesse vanno intercettate con espressioni regolari, non con
# corrispondenze letterali.
#
# PERCHE'
# L'elenco letterale conteneva "conferma che" e ha lasciato passare
# "confermano che", in un testo realmente prodotto da qwen2.5:3b sul caso
# pilota. Il modello scriveva: «Questi dati confermano che l'interazione
# ipotizzata e' coerente e affidabile» — cioe' presentava un'ipotesi
# computazionale come un risultato accertato, che e' precisamente cio' che
# questo strumento non deve mai fare.
#
# Le radici sono volutamente generose. Il costo di un falso positivo e' un
# ripiego sul testo deterministico; il costo di un falso negativo e' un
# documento che afferma cio' che non puo' affermare.
# Espressioni di efficacia in forma flessa o nominale.
#
# PERCHE' NON BASTAVA L'ELENCO LETTERALE
# L'elenco copriva "efficacia dimostrata", "efficacia clinica" e "e' efficace",
# e ha lasciato passare l'uso NOMINALE: qwen2.5:7b-instruct ha scritto «il
# meccanismo ipotizzato per l'efficacia del sirolimus» e «ulteriori studi per
# confermare l'efficacia». Sono entrambe formule che presentano come oggetto di
# indagine un'efficacia data per esistente, ed e' precisamente cio' che il
# disclaimer del progetto dichiara non debba mai comparire.
#
# La radice e' bandita senza eccezioni. Il costo di un falso positivo e' un
# ripiego sul testo deterministico; il costo di un falso negativo e' un
# documento che parla di efficacia di un farmaco mai sperimentato per quella
# malattia. Il generatore deterministico non usa mai questa radice, quindi il
# ripiego resta sempre disponibile.
FORBIDDEN_PATTERNS = [
    re.compile(r"efficac\w*"),
    re.compile(r"terapeuticamente\s+\w+"),
]

OVERCLAIM_PATTERNS = [
    # conferma / confermano / confermato / confermerebbe ... che|questa|l'ipotesi
    # CONFERMARE: conta l'oggetto, non il verbo.
    #
    # «L'interazione farmaco-gene e' confermata da otto database» e' vera e
    # verificabile: e' un'affermazione sui dati. «La coerenza del meccanismo e'
    # confermata» non lo e': la coerenza e' il risultato di un'euristica, e
    # nulla in questo strumento la conferma.
    #
    # Un divieto indiscriminato sul verbo era stato provato e scartato: con
    # quello, qwen2.5:7b falliva la validazione due volte per candidato e
    # ripiegava sempre, anche quando scriveva cose corrette. Un validatore che
    # respinge tutto non protegge nessuno, rende solo inutile il modello.
    re.compile(r"conferm\w+\s+(che|quest[aoie])"),
    re.compile(
        r"conferm\w+\s+(l.ipotesi|il meccanismo|la coerenza|la direzione|"
        r"la plausibilita|l.efficacia)"
    ),
    re.compile(
        r"(l.ipotesi|il meccanismo|la coerenza|la direzione|la plausibilita)"
        r"(?:\s+\w+){0,3}\s+(?:e.?|è|risulta|appare|viene)\s+conferm\w+"
    ),
    re.compile(r"altamente\s+(probabile|verosimile|plausibile)"),
    re.compile(r"dimostr\w*\s+(che|quest[aoie])"),
    re.compile(r"prov\w*\s+(che|quest[aoie])"),
    re.compile(r"attest\w*\s+(che|quest[aoie])"),
    # "e' coerente e affidabile", "ipotesi affidabile", "risultato affidabile"
    re.compile(r"affidabil\w*"),
    re.compile(r"(e.|è)\s+(provat\w+|dimostrat\w+|accertat\w+|comprovat\w+)"),
    re.compile(r"(?:risulta|appare)\s+(provat\w+|dimostrat\w+|accertat\w+)"),
    # inglese
    re.compile(r"confirm(s|ed|ing)?\s+(that|this)"),
    re.compile(r"demonstrat\w*\s+(that|this)"),
    re.compile(r"prov(es|en|ing)\s+(that|this)"),
    re.compile(r"\breliable\b"),
]


@dataclass
class Violation:
    kind: str  # unknown_pmid | unknown_identifier | unknown_gene | unknown_drug |
    #            forbidden_language | overclaim | missing_subject
    detail: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.detail}"


@dataclass
class ValidationResult:
    ok: bool
    violations: list[Violation] = field(default_factory=list)
    # Falso quando mancano i vocabolari: il controllo e' stato piu' debole e il
    # chiamante deve poterlo sapere invece di credere a un "ok" pieno.
    full_vocabulary: bool = True

    def summary(self) -> str:
        if self.ok:
            return "validazione superata" + (
                "" if self.full_vocabulary else " (vocabolari parziali)"
            )
        return "; ".join(str(v) for v in self.violations)


def _normalize_identifier(token: str) -> str:
    t = token.upper()
    if t.startswith("ORPHANET:"):
        t = "ORPHA:" + t.split(":", 1)[1]
    return t


def validate(
    text: str,
    bundle: EvidenceBundle,
    *,
    drug_name: str | None = None,
    known_genes: set[str] | None = None,
    known_drugs: set[str] | None = None,
    shown_context: str | None = None,
) -> ValidationResult:
    """Verifica che il testo generato non affermi nulla che non gli sia stato mostrato.

    `known_genes` e `known_drugs` sono i vocabolari completi (HGNC, DGIdb).
    Servono a riconoscere che un token E' un gene o un farmaco, prima di poter
    dire che non appartiene al bundle.

    `shown_context` e' il testo effettivamente consegnato al modello. Il suo
    contenuto viene aggiunto al vocabolario consentito.

    PERCHE' SERVE
    L'invariante corretta non e' "il modello puo' citare cio' che sta nel
    bundle", ma **"il modello puo' citare cio' che gli e' stato mostrato"**.
    Le due cose divergono: la motivazione curata della coerenza direzionale
    contiene la catena `TSC1-TSC2 -> RHEB-GTP -> mTORC1`, quindi il modello
    vede RHEB, ma RHEB non e' ne' un gene causale ne' un bersaglio e non
    compariva nel vocabolario. Il risultato era che il validatore respingeva
    generazioni corrette per aver usato un fatto fornito da noi stessi.

    Derivare il vocabolario da cio' che e' stato mostrato rende l'invariante
    vera per costruzione, invece di affidarla a una lista mantenuta a mano che
    puo' andare fuori sincrono con il prompt.
    """
    violations: list[Violation] = []
    lowered = text.lower()

    allowed_pmids = bundle.allowed_pmids()
    allowed_ids = {_normalize_identifier(i) for i in bundle.allowed_identifiers()}
    allowed_genes = {g.upper() for g in bundle.allowed_genes()}
    allowed_drugs = {d.lower() for d in bundle.allowed_drugs()}

    if shown_context:
        allowed_pmids |= set(PMID_RE.findall(shown_context))
        allowed_pmids |= set(BARE_PMID_RE.findall(shown_context))
        allowed_ids |= {_normalize_identifier(i) for i in IDENTIFIER_RE.findall(shown_context)}
        allowed_genes |= set(GENE_TOKEN_RE.findall(shown_context))
        allowed_drugs |= {w.lower() for w in WORD_RE.findall(shown_context)}

    # --- 1. PMID
    cited = set(PMID_RE.findall(text)) | set(BARE_PMID_RE.findall(text))
    for pmid in sorted(cited - allowed_pmids):
        violations.append(
            Violation("unknown_pmid", f"PMID {pmid} non presente nell'evidence bundle")
        )

    # --- 2. identificatori strutturati
    for raw in IDENTIFIER_RE.findall(text):
        ident = _normalize_identifier(raw)
        if ident not in allowed_ids:
            violations.append(
                Violation("unknown_identifier", f"identificatore {raw} non presente nel bundle")
            )

    # --- 3. simboli genici
    if known_genes:
        known_upper = {g.upper() for g in known_genes}
        for token in set(GENE_TOKEN_RE.findall(text)):
            if token in known_upper and token not in allowed_genes:
                violations.append(
                    Violation("unknown_gene", f"gene {token} citato ma non presente nel bundle")
                )

    # --- 4. nomi di farmaco
    if known_drugs:
        known_lower = {
            d.lower()
            for d in known_drugs
            if len(d) >= MIN_DRUG_TOKEN_LENGTH and d.lower() not in GENERIC_DRUG_NAMES
        }
        for token in {w.lower() for w in WORD_RE.findall(text)}:
            if token in known_lower and token not in allowed_drugs:
                violations.append(
                    Violation(
                        "unknown_drug", f"farmaco '{token}' citato ma non presente nel bundle"
                    )
                )

    # --- 5. linguaggio vietato
    for phrase in FORBIDDEN_PHRASES:
        if phrase in lowered:
            violations.append(
                Violation("forbidden_language", f"espressione di efficacia clinica: «{phrase}»")
            )
    for phrase in OVERCLAIM_PHRASES:
        if phrase in lowered:
            violations.append(
                Violation("overclaim", f"un'ipotesi presentata come fatto: «{phrase}»")
            )
    for pattern in FORBIDDEN_PATTERNS:
        match = pattern.search(lowered)
        if match:
            violations.append(
                Violation(
                    "forbidden_language",
                    f"espressione di efficacia clinica: «{match.group(0)}»",
                )
            )
    for pattern in OVERCLAIM_PATTERNS:
        match = pattern.search(lowered)
        if match:
            violations.append(
                Violation("overclaim", f"un'ipotesi presentata come fatto: «{match.group(0)}»")
            )

    # --- 6. il testo deve parlare del farmaco che gli e' stato assegnato
    if drug_name and drug_name.lower() not in lowered:
        violations.append(
            Violation("missing_subject", f"il testo non menziona il candidato '{drug_name}'")
        )

    return ValidationResult(
        ok=not violations,
        violations=violations,
        full_vocabulary=bool(known_genes) and bool(known_drugs),
    )


def load_vocabularies(con) -> tuple[set[str], set[str]]:
    """Vocabolari completi dallo store, per la modalita' di validazione forte."""
    genes = {r[0] for r in con.execute("SELECT symbol FROM genes").fetchall() if r[0]}
    drugs = {
        r[0].lower()
        for r in con.execute("SELECT DISTINCT drug_name FROM dgidb_interactions").fetchall()
        if r[0]
    }
    return genes, drugs
