"""
Scraper Package
===============

Importing this package triggers auto-registration of all built-in scrapers
so that :func:`scraper.registry.list_sources` returns the full list.
"""

# Import scraper modules to trigger @register side-effects.
import scraper.odd  # noqa: F401
import scraper.seek  # noqa: F401
