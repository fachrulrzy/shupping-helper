"""
Scraper Registry
================

Central registry that maps source slugs (e.g. ``"seek"``, ``"tokopedia"``)
to their scraper classes.  ``main.py`` uses this to auto-discover available
sources without hardcoded imports.

Adding a new source only requires:
1. Create the scraper class (subclass of BaseScraper or ShopifyScraper).
2. Call ``register(MyScraperClass)`` in this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scraper.base import BaseScraper

# slug → scraper class
_REGISTRY: dict[str, type[BaseScraper]] = {}


def register(cls: type[BaseScraper]) -> type[BaseScraper]:
    """Register a scraper class in the global registry.

    Can be used as a decorator::

        @register
        class MyStoreScraper(ShopifyScraper):
            SLUG = "mystore"
            ...
    """
    if not cls.SLUG:
        raise ValueError(f"{cls.__name__} must define a non-empty SLUG.")
    _REGISTRY[cls.SLUG] = cls
    return cls


def get_scraper(slug: str) -> BaseScraper:
    """Return a *new instance* of the scraper registered under *slug*.

    Raises ``KeyError`` if the slug is not registered.
    """
    if slug not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(
            f"Unknown source '{slug}'. Available: {available}"
        )
    return _REGISTRY[slug]()


def list_sources() -> list[str]:
    """Return all registered source slugs, sorted alphabetically."""
    return sorted(_REGISTRY)


def list_scrapers() -> dict[str, type[BaseScraper]]:
    """Return the full registry mapping (slug → class)."""
    return dict(_REGISTRY)
