"""Publisher-specific scraper adapters.

- ALPScraper       American Legal Publishing (codelibrary.amlegal.com)
- MunicodeScraper  Municode (library.municode.com / api.municode.com)
"""

from .alp import ALPScraper
from .municode import MunicodeScraper

__all__ = ["ALPScraper", "MunicodeScraper"]
