"""
Seek Indonesia Scraper
======================

Shopify-powered scraper for `seekindonesia.com <https://seekindonesia.com>`_.

This module is intentionally tiny — all the heavy lifting is done by
:class:`~scraper.shopify_base.ShopifyScraper`.  Adding this store was
literally just setting three class attributes.
"""

from __future__ import annotations

from scraper.registry import register
from scraper.shopify_base import ShopifyScraper


@register
class SeekScraper(ShopifyScraper):
    """Scraper for Seek Indonesia (seekindonesia.com)."""

    NAME = "Seek Indonesia"
    SLUG = "seek"
    BASE_URL = "https://seekindonesia.com"


# ---------------------------------------------------------------------------
# Backward-compatible module-level functions
# ---------------------------------------------------------------------------

_instance = SeekScraper()


def search_seek(keyword: str, max_pages: int = 1) -> list[dict]:
    """Search Seek Indonesia — delegates to :class:`SeekScraper`."""
    return _instance.search(keyword, max_pages=max_pages)


def export_to_csv(products: list[dict], filepath: str) -> "Path":  # noqa: F821
    """Export to CSV — delegates to :class:`SeekScraper`."""
    return _instance.export_to_csv(products, filepath)