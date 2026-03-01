"""
Base Scraper Module
===================

Provides the abstract ``BaseScraper`` class that all source-specific scrapers
must extend.  Shared logic (price parsing, delays, retries, CSV export, HTTP
helpers) lives here so it is never duplicated.
"""

from __future__ import annotations

import abc
import csv
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Curated desktop User-Agent strings
# ---------------------------------------------------------------------------

DESKTOP_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


# ---------------------------------------------------------------------------
# BaseScraper abstract class
# ---------------------------------------------------------------------------


class BaseScraper(abc.ABC):
    """Abstract base class for all product scrapers.

    Subclasses **must** define the class-level attributes ``NAME``,
    ``SLUG``, and ``BASE_URL``, and implement the :meth:`search` method.

    Shared helpers (price parsing, delays, retries, headers, CSV export)
    are provided so that subclasses never need to re-implement them.

    Attributes
    ----------
    NAME : str
        Human-readable name shown in terminal output (e.g. "Seek Indonesia").
    SLUG : str
        Short identifier used in CLI ``--source`` (e.g. "seek").
    BASE_URL : str
        Root URL of the website (e.g. "https://seekindonesia.com").
    """

    # Subclasses must set these.
    NAME: str = ""
    SLUG: str = ""
    BASE_URL: str = ""

    # Configurable per-subclass.
    MIN_DELAY: float = 0.5
    MAX_DELAY: float = 1.5
    MAX_RETRIES: int = 3
    RETRY_BACKOFF: float = 2.0

    # Standard fields that every scraper product dict should contain.
    STANDARD_FIELDS: list[str] = [
        "name", "price", "store", "rating", "url", "is_ad", "sold", "reviews",
    ]

    # Extended fields (optional – Shopify scrapers add these).
    EXTENDED_FIELDS: list[str] = [
        "original_price", "is_on_sale", "brand", "image_url",
        "in_stock", "sizes", "colours", "product_type", "tags",
    ]

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"scraper.{self.SLUG}")

    # ------------------------------------------------------------------
    # Abstract method
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def search(self, keyword: str, max_pages: int = 1) -> list[dict]:
        """Search for products matching *keyword*.

        Parameters
        ----------
        keyword : str
            The product search term.
        max_pages : int, optional
            How many pages of results to retrieve (default ``1``).

        Returns
        -------
        list[dict]
            Each dict contains at minimum the keys in ``STANDARD_FIELDS``.
        """

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def random_delay(self) -> None:
        """Sleep for a random interval between ``MIN_DELAY`` and ``MAX_DELAY``."""
        delay = random.uniform(self.MIN_DELAY, self.MAX_DELAY)
        self.logger.debug("Sleeping %.2f s …", delay)
        time.sleep(delay)

    @staticmethod
    def random_ua() -> str:
        """Return a random desktop User-Agent string."""
        return random.choice(DESKTOP_USER_AGENTS)

    def build_headers(self) -> dict[str, str]:
        """Return browser-like HTTP headers with a rotated User-Agent."""
        return {
            "User-Agent": self.random_ua(),
            "Accept": "application/json, text/html, */*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
            "Referer": self.BASE_URL,
        }

    @staticmethod
    def safe_json(resp: requests.Response) -> dict | list:
        """Parse *resp* as JSON, raising ``ValueError`` on non-JSON content."""
        content_type = resp.headers.get("content-type", "")
        if "application/json" not in content_type:
            raise ValueError(
                f"Non-JSON response (Content-Type: {content_type}, "
                f"status {resp.status_code})"
            )
        return resp.json()

    @staticmethod
    def parse_price(raw: str | int | float | None) -> int:
        """Convert various price representations to a plain integer (IDR).

        Handles both decimal notation (``"2750000.00"``) and Indonesian
        thousand-separator notation (``"Rp 2.200.000"``).

        Examples
        --------
        >>> BaseScraper.parse_price("Rp 1.450.000")
        1450000
        >>> BaseScraper.parse_price("2750000.00")
        2750000
        >>> BaseScraper.parse_price("Rp 2.200.000")
        2200000
        >>> BaseScraper.parse_price(880000)
        880000
        """
        if raw is None:
            return 0
        if isinstance(raw, (int, float)):
            return int(raw)

        text = str(raw).strip()

        # Strip everything except digits, dots, and commas.
        cleaned = re.sub(r"[^\d.,]", "", text)
        if not cleaned:
            return 0

        # Count dots — if more than one, they are thousand separators (IDR).
        dot_count = cleaned.count(".")
        if dot_count > 1:
            # "2.200.000" → "2200000"
            cleaned = cleaned.replace(".", "")
        elif dot_count == 1:
            # Could be decimal ("2750000.00") or single thousand sep ("800.000").
            # Heuristic: if last dot has exactly 3 digits after it, it's a
            # thousand separator; otherwise it's a decimal point.
            parts = cleaned.split(".")
            if len(parts[1]) == 3:
                cleaned = cleaned.replace(".", "")
            # else keep dot as decimal

        # Commas are always thousand separators (e.g. "1,450,000").
        cleaned = cleaned.replace(",", "")

        if not cleaned:
            return 0
        return int(float(cleaned))

    @staticmethod
    def parse_rating(raw: Any) -> float:
        """Safely parse a rating value to float, defaulting to ``0.0``."""
        if raw is None:
            return 0.0
        try:
            return round(float(raw), 1)
        except (ValueError, TypeError):
            return 0.0

    def retry(
        self,
        fn: Any,
        *args: Any,
        label: str = "",
        **kwargs: Any,
    ) -> Any:
        """Call *fn* with retries and exponential back-off.

        Parameters
        ----------
        fn : callable
            The function to call.
        label : str
            Label for log messages (e.g. ``"GQL"``).
        *args, **kwargs
            Forwarded to *fn*.

        Returns
        -------
        The return value of *fn* on the first successful call.

        Raises
        ------
        Exception
            Re-raised from the last failed attempt.
        """
        tag = f"[{label}] " if label else ""
        last_exc: Exception | None = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                self.logger.warning(
                    "%sAttempt %d failed: %s", tag, attempt, exc
                )
                if attempt < self.MAX_RETRIES:
                    backoff = self.RETRY_BACKOFF ** attempt + random.uniform(0, 1)
                    self.logger.info("%sRetrying in %.1f s …", tag, backoff)
                    time.sleep(backoff)
                else:
                    self.logger.error(
                        "%sAll %d attempts exhausted.", tag, self.MAX_RETRIES
                    )
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    def export_to_csv(
        self, products: list[dict], filepath: str | Path
    ) -> Path:
        """Export *products* to a CSV file at *filepath*.

        Automatically detects which fields are present in the product dicts
        and writes only those columns.

        Returns the resolved path of the written file.
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Determine fieldnames from the first product, falling back to the
        # standard set.
        if products:
            fieldnames = list(products[0].keys())
        else:
            fieldnames = self.STANDARD_FIELDS

        with open(filepath, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=fieldnames, extrasaction="ignore"
            )
            writer.writeheader()
            for product in products:
                row = dict(product)
                # Serialise list fields for CSV.
                for key in ("sizes", "colours", "tags"):
                    if isinstance(row.get(key), list):
                        row[key] = ", ".join(str(v) for v in row[key])
                writer.writerow(row)

        self.logger.info("Exported %d products → %s", len(products), filepath)
        return filepath.resolve()

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<{type(self).__name__} slug={self.SLUG!r} url={self.BASE_URL!r}>"
