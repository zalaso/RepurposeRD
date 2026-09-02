"""RepurposeRD — generatore di ipotesi di riposizionamento terapeutico.

Ipotesi di ricerca computazionali, non consigli medici. Vedi DISCLAIMER.md.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("RepurposeRD")
except PackageNotFoundError:  # eseguito da sorgente, senza installazione
    __version__ = "0.0.0+sorgente"

__all__ = ["__version__"]
