"""Backend per la generazione in linguaggio naturale.

L'inferenza e' locale per vincolo di progetto, ma il backend e' astratto per una
ragione piu' pratica: legare la pipeline a un singolo runtime significherebbe
che chi non ha quel runtime non puo' eseguire nulla. Qui ci sono tre backend, e
uno di essi non richiede alcun modello.

  ollama             — http://localhost:11434, il default
  openai-compatible  — LM Studio, llama-server di llama.cpp, qualunque server
                       che esponga /v1/chat/completions in locale
  template           — nessun modello: prosa deterministica costruita dalle
                       stesse evidenze. Non e' un ripiego degradato, e' il
                       fallback verificabile: cio' che scrive e' esattamente
                       cio' che c'e' nel bundle, per costruzione.

Nessun backend ha accesso a strumenti di ricerca. Il modello scrive, non cerca.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod

import httpx


class LLMUnavailable(RuntimeError):
    pass


class LLMBackend(ABC):
    name: str = "abstract"

    @abstractmethod
    def generate(self, system: str, prompt: str, max_tokens: int = 320) -> str: ...

    def available(self) -> bool:
        return True

    def describe(self) -> str:
        return self.name


class TemplateBackend(LLMBackend):
    """Nessun modello linguistico.

    Il testo viene assemblato in `prompts.render_template` a partire dai campi
    strutturati del candidato. Deterministico, riproducibile, e incapace di
    inventare per costruzione, perche' non genera: ricopia.
    """

    name = "template"

    def generate(self, system: str, prompt: str, max_tokens: int = 320) -> str:
        raise NotImplementedError(
            "TemplateBackend non genera testo: il report usa render_template() direttamente."
        )


class OllamaBackend(LLMBackend):
    """Backend Ollama.

    Il timeout predefinito e' volutamente alto (10 minuti). Su una CPU portatile
    senza accelerazione un modello da 7 miliardi di parametri puo' impiegare
    diversi minuti per un solo paragrafo, e un timeout stretto trasformerebbe
    "lento" in "non funziona". Chi ha hardware adeguato non se ne accorge;
    chi non ce l'ha ottiene comunque un risultato invece di un errore.
    """

    name = "ollama"

    def __init__(
        self,
        model: str = "qwen2.5:7b-instruct",
        host: str = "http://localhost:11434",
        temperature: float = 0.2,
        timeout: float = 600.0,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        # Temperatura bassa di proposito: qui la creativita' e' un difetto, non
        # una qualita'. Il compito e' riformulare evidenze, non arricchirle.
        self.temperature = temperature
        self.timeout = timeout

    def available(self) -> bool:
        try:
            resp = httpx.get(f"{self.host}/api/tags", timeout=5.0)
            resp.raise_for_status()
            models = {m.get("name", "") for m in resp.json().get("models", [])}
            base = {m.split(":")[0] for m in models}
            return self.model in models or self.model.split(":")[0] in base
        except (httpx.HTTPError, ValueError, KeyError):
            return False

    def describe(self) -> str:
        return f"ollama/{self.model} @ {self.host}"

    def generate(self, system: str, prompt: str, max_tokens: int = 320) -> str:
        try:
            resp = httpx.post(
                f"{self.host}/api/chat",
                timeout=self.timeout,
                json={
                    "model": self.model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "options": {"temperature": self.temperature, "num_predict": max_tokens},
                },
            )
            resp.raise_for_status()
            return (resp.json().get("message", {}).get("content") or "").strip()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Ollama non raggiungibile su {self.host}: {exc}") from exc
        except (ValueError, KeyError) as exc:
            raise LLMUnavailable(f"Risposta di Ollama non interpretabile: {exc}") from exc


class OpenAICompatibleBackend(LLMBackend):
    """Per LM Studio, llama-server e simili, in locale.

    Il default punta a localhost: se qualcuno vi indirizza un endpoint remoto,
    sta uscendo dal vincolo "100% locale" e deve farlo consapevolmente.
    """

    name = "openai-compatible"

    def __init__(
        self,
        model: str = "local-model",
        base_url: str = "http://localhost:1234/v1",
        api_key: str = "not-needed",
        temperature: float = 0.2,
        timeout: float = 600.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout

    def available(self) -> bool:
        try:
            resp = httpx.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=5.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def describe(self) -> str:
        return f"openai-compatible/{self.model} @ {self.base_url}"

    def generate(self, system: str, prompt: str, max_tokens: int = 320) -> str:
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                content=json.dumps(
                    {
                        "model": self.model,
                        "temperature": self.temperature,
                        "max_tokens": max_tokens,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                    }
                ),
            )
            resp.raise_for_status()
            return (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Endpoint non raggiungibile su {self.base_url}: {exc}") from exc
        except (ValueError, KeyError, IndexError) as exc:
            raise LLMUnavailable(f"Risposta non interpretabile: {exc}") from exc


def make_backend(
    kind: str,
    model: str | None = None,
    host: str | None = None,
    timeout: float | None = None,
) -> LLMBackend:
    kind = (kind or "template").lower()
    if kind == "template":
        return TemplateBackend()
    if kind == "ollama":
        kwargs: dict = {}
        if model:
            kwargs["model"] = model
        if host:
            kwargs["host"] = host
        if timeout:
            kwargs["timeout"] = timeout
        return OllamaBackend(**kwargs)
    if kind in {"openai-compatible", "openai", "lmstudio", "llamacpp"}:
        kwargs = {}
        if model:
            kwargs["model"] = model
        if host:
            kwargs["base_url"] = host
        if timeout:
            kwargs["timeout"] = timeout
        return OpenAICompatibleBackend(**kwargs)
    raise ValueError(
        f"Backend LLM sconosciuto: {kind!r}. Validi: template, ollama, openai-compatible."
    )
