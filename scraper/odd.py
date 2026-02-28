"""
Our Daily Dose (ourdailydose.net) Product Scraper
=================================================

Scrapes product data from `ourdailydose.net <https://www.ourdailydose.net>`_,
a Magento-powered Indonesian sneaker store.

Uses HTML scraping of the search results page since Magento doesn't expose
a public JSON API like Shopify.
"""

from __future__ import annotations

import random
import re
import time
from typing import Any
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from scraper.base import BaseScraper
from scraper.registry import register


@register
class OddScraper(BaseScraper):
    """Scraper for Our Daily Dose (ourdailydose.net).

    Uses two strategies:
    1. Static HTML scraping (requests + BS4)
    2. Playwright headless browser (fallback)
    """

    NAME = "Our Daily Dose"
    SLUG = "odd"
    BASE_URL = "https://www.ourdailydose.net"

    # Magento search URL.
    SEARCH_URL = "https://www.ourdailydose.net/catalogsearch/result/"

    # Be polite — moderate delays.
    MIN_DELAY: float = 1.0
    MAX_DELAY: float = 2.0

    # ------------------------------------------------------------------
    # Public API — implements BaseScraper.search()
    # ------------------------------------------------------------------

    def search(self, keyword: str, max_pages: int = 1) -> list[dict]:
        """Search Our Daily Dose using HTML scraping with Playwright fallback."""
        all_results: list[dict] = []

        for page_num in range(1, max_pages + 1):
            if page_num > 1:
                self.random_delay()

            products: list[dict] = []

            # ---- Strategy 1: Static HTML ----
            try:
                products = self._search_via_html(keyword, page=page_num)
                if products:
                    self.logger.info(
                        "[HTML] Page %d → %d products.", page_num, len(products)
                    )
            except Exception as exc:
                self.logger.warning("[HTML] Failed for page %d: %s", page_num, exc)

            # ---- Strategy 2: Playwright fallback ----
            if not products:
                self.logger.info("[Playwright] Falling back to headless browser …")
                self.random_delay()
                try:
                    products = self._search_via_playwright(keyword, page=page_num)
                    if products:
                        self.logger.info(
                            "[Playwright] Page %d → %d products.",
                            page_num, len(products),
                        )
                except Exception as exc:
                    self.logger.warning(
                        "[Playwright] Failed for page %d: %s", page_num, exc
                    )

            if not products:
                self.logger.warning(
                    "No results for page %d. All strategies failed.", page_num
                )

            all_results.extend(products)

        # Deduplicate by URL (Magento can render the same card multiple times).
        seen_urls: set[str] = set()
        unique: list[dict] = []
        for p in all_results:
            url = p.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique.append(p)
            elif not url:
                unique.append(p)

        return unique

    # ------------------------------------------------------------------
    # Strategy 1: Static HTML
    # ------------------------------------------------------------------

    def _search_via_html(self, keyword: str, page: int = 1) -> list[dict]:
        """Scrape ODD search results via requests + BeautifulSoup."""
        params: dict[str, Any] = {"q": keyword}
        if page > 1:
            params["p"] = page

        headers = self.build_headers()
        # Override Accept for HTML pages.
        headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        )

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                self.logger.info(
                    "[HTML] Searching '%s' page %d (attempt %d) …",
                    keyword, page, attempt,
                )
                resp = requests.get(
                    self.SEARCH_URL,
                    headers=headers,
                    params=params,
                    timeout=20,
                )
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "lxml")
                return self._parse_product_cards(soup)

            except requests.RequestException as exc:
                self.logger.warning("[HTML] Attempt %d failed: %s", attempt, exc)
                if attempt < self.MAX_RETRIES:
                    backoff = self.RETRY_BACKOFF ** attempt + random.uniform(0, 1)
                    time.sleep(backoff)
                else:
                    raise

        return []

    def _parse_product_cards(self, soup: BeautifulSoup) -> list[dict]:
        """Parse product cards from ODD Magento search results."""
        results: list[dict] = []

        # Magento product list selectors.
        cards = soup.select(".product-item, .product-item-info, li.item.product")
        if not cards:
            # Fallback: broader search.
            cards = soup.select("[class*='product']")
            cards = [c for c in cards if c.select_one("a[href*='.html']")]

        self.logger.debug("Found %d product card candidates.", len(cards))

        for card in cards:
            try:
                product = self._parse_one_card(card)
                if product and product["name"] != "N/A":
                    results.append(product)
            except Exception as exc:
                self.logger.debug("Skipping card: %s", exc)
                continue

        return results

    def _parse_one_card(self, card: BeautifulSoup) -> dict | None:
        """Extract product info from a single Magento product card."""
        # ---- Name ----
        name_el = (
            card.select_one(".product-item-link")
            or card.select_one(".product-name a")
            or card.select_one("a.product")
            or card.select_one("h2 a, h3 a")
        )
        if not name_el:
            return None
        name = name_el.get_text(strip=True)
        if not name:
            return None

        # ---- URL ----
        url = name_el.get("href", "")
        if url and not url.startswith("http"):
            url = urljoin(self.BASE_URL, url)

        # ---- Price ----
        price_el = (
            card.select_one(".price-wrapper .price")
            or card.select_one(".special-price .price")
            or card.select_one(".normal-price .price")
            or card.select_one(".price")
        )
        price = self.parse_price(
            price_el.get_text(strip=True) if price_el else None
        )

        # ---- Original price (for sale detection) ----
        original_price = 0
        old_price_el = card.select_one(".old-price .price")
        if old_price_el:
            original_price = self.parse_price(old_price_el.get_text(strip=True))
        is_on_sale = original_price > 0 and original_price > price

        # ---- Brand ----
        brand_el = (
            card.select_one(".product-item-brand")
            or card.select_one("[class*='brand']")
        )
        brand = brand_el.get_text(strip=True) if brand_el else ""

        # If brand not found in a dedicated element, try to infer from name.
        if not brand:
            brand = self._infer_brand(name)

        # ---- Image ----
        img_el = card.select_one("img.product-image-photo, img[src*='product']")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src") or ""

        # ---- Limited tag ----
        is_limited = bool(card.select_one("[class*='limited'], .label-limited"))
        if not is_limited:
            card_text = card.get_text(separator=" ", strip=True).lower()
            is_limited = "limited" in card_text

        return {
            "name": name,
            "price": price,
            "original_price": original_price,
            "is_on_sale": is_on_sale,
            "store": self.NAME,
            "brand": brand,
            "rating": 0.0,
            "url": url,
            "image_url": image_url,
            "is_ad": False,
            "sold": "",
            "reviews": 0,
            "in_stock": True,  # If it's in search results, it's in stock.
            "is_limited": is_limited,
        }

    @staticmethod
    def _infer_brand(product_name: str) -> str:
        """Try to infer the brand from the product name prefix."""
        known_brands = [
            "Adidas", "Nike", "New Balance", "Puma", "Converse", "Reebok",
            "Vans", "Asics", "Onitsuka Tiger", "Saucony", "Salomon",
            "Karhu", "Autry", "Diadora", "Filling Pieces", "Hoka",
            "On Running", "Birkenstock", "Clarks", "Dr. Martens",
        ]
        name_lower = product_name.lower()
        for brand in known_brands:
            if name_lower.startswith(brand.lower()):
                return brand
        return "N/A"

    # ------------------------------------------------------------------
    # Strategy 2: Playwright fallback
    # ------------------------------------------------------------------

    def _search_via_playwright(self, keyword: str, page: int = 1) -> list[dict]:
        """Scrape ODD search using Playwright headless Chromium."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.error(
                "Playwright is not installed. "
                "Run: pip install playwright && python -m playwright install chromium"
            )
            return []

        params = f"?q={quote_plus(keyword)}"
        if page > 1:
            params += f"&p={page}"
        url = f"{self.SEARCH_URL}{params}"

        results: list[dict] = []

        self.logger.info("[Playwright] Launching headless browser for page %d …", page)

        with sync_playwright() as pw:
            launch_kwargs: dict[str, Any] = {"headless": True}
            try:
                browser = pw.chromium.launch(channel="chrome", **launch_kwargs)
            except Exception:
                browser = pw.chromium.launch(**launch_kwargs)

            context = browser.new_context(
                user_agent=self.random_ua(),
                viewport={"width": 1366, "height": 768},
                locale="id-ID",
                java_script_enabled=True,
            )
            page_obj = context.new_page()

            try:
                page_obj.goto(url, wait_until="domcontentloaded", timeout=45_000)
                try:
                    page_obj.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    pass

                # Scroll to load lazy content.
                for _ in range(4):
                    page_obj.evaluate("window.scrollBy(0, 800)")
                    page_obj.wait_for_timeout(random.randint(800, 1200))
                page_obj.wait_for_timeout(2000)

                content = page_obj.content()
                soup = BeautifulSoup(content, "lxml")
                results = self._parse_product_cards(soup)

            except Exception as exc:
                self.logger.error("[Playwright] Error: %s", exc)
            finally:
                context.close()
                browser.close()

        return results


# ---------------------------------------------------------------------------
# Backward-compatible module-level functions
# ---------------------------------------------------------------------------

_instance = OddScraper()


def search_odd(keyword: str, max_pages: int = 1) -> list[dict]:
    """Search Our Daily Dose — delegates to :class:`OddScraper`."""
    return _instance.search(keyword, max_pages=max_pages)


def export_to_csv(products: list[dict], filepath: str) -> "Path":  # noqa: F821
    """Export to CSV — delegates to :class:`OddScraper`."""
    return _instance.export_to_csv(products, filepath)
