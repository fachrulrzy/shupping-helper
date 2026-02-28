"""
Shopify Base Scraper
====================

Reusable scraper for **any** Shopify-powered store.  Subclasses only need
to set ``NAME``, ``SLUG``, and ``BASE_URL`` — all Shopify-specific logic
(Search Suggest API, Products JSON pagination, Playwright fallback) is
handled here.

Example
-------
::

    class SeekScraper(ShopifyScraper):
        NAME = "Seek Indonesia"
        SLUG = "seek"
        BASE_URL = "https://seekindonesia.com"
"""

from __future__ import annotations

import json
import random
from typing import Any
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from scraper.base import BaseScraper

# ---------------------------------------------------------------------------
# ShopifyScraper
# ---------------------------------------------------------------------------

# Shopify constants.
_PRODUCTS_PER_PAGE: int = 250
_SEARCH_SUGGEST_LIMIT: int = 10


class ShopifyScraper(BaseScraper):
    """Base scraper for Shopify-powered stores.

    Implements three search strategies that apply to any Shopify site:

    1. **Search Suggest API** — ``/search/suggest.json`` (fast, max 10)
    2. **Products JSON API** — ``/products.json`` with pagination
    3. **Playwright fallback** — headless browser for blocked APIs

    Subclasses typically only override class attributes::

        class MyStoreScraper(ShopifyScraper):
            NAME = "My Store"
            SLUG = "mystore"
            BASE_URL = "https://mystore.com"
    """

    # Shopify stores are generally polite — lighter delays are fine.
    MIN_DELAY: float = 0.5
    MAX_DELAY: float = 1.5

    # ------------------------------------------------------------------
    # Public API — implements BaseScraper.search()
    # ------------------------------------------------------------------

    def search(self, keyword: str, max_pages: int = 1) -> list[dict]:
        """Search this Shopify store using the three-strategy cascade."""
        all_results: list[dict] = []

        # ---- Strategy 1: Search Suggest API ----
        try:
            products = self._search_via_suggest(keyword)
            if products:
                self.logger.info(
                    "[Suggest] → %d product(s) found.", len(products)
                )
                all_results.extend(products)
        except Exception as exc:
            self.logger.warning("[Suggest] Failed: %s", exc)

        # ---- Strategy 2: Products JSON (richer data) ----
        try:
            products = self._search_via_products_json(keyword, max_pages)
            if products:
                self.logger.info(
                    "[JSON] → %d product(s) found.", len(products)
                )
                # Merge — avoid duplicates by product name.
                existing_names = {r["name"].lower() for r in all_results}
                for p in products:
                    if p["name"].lower() not in existing_names:
                        all_results.append(p)
                        existing_names.add(p["name"].lower())
                    else:
                        # Enrich existing entry with richer data.
                        for existing in all_results:
                            if existing["name"].lower() == p["name"].lower():
                                for key in ("sizes", "colours", "image_url", "in_stock"):
                                    if p.get(key) and not existing.get(key):
                                        existing[key] = p[key]
                                break
        except Exception as exc:
            self.logger.warning("[JSON] Failed: %s", exc)

        # ---- Strategy 3: Playwright fallback ----
        if not all_results:
            self.logger.info("[Playwright] Falling back to headless browser …")
            self.random_delay()
            try:
                products = self._search_via_playwright(keyword)
                if products:
                    self.logger.info(
                        "[Playwright] → %d product(s) found.", len(products)
                    )
                    all_results.extend(products)
            except Exception as exc:
                self.logger.warning("[Playwright] Failed: %s", exc)

        if not all_results:
            self.logger.warning(
                "No results for '%s'. All strategies failed.", keyword
            )

        return all_results

    # ------------------------------------------------------------------
    # Strategy 1: Shopify Search Suggest API
    # ------------------------------------------------------------------

    def _search_via_suggest(self, keyword: str) -> list[dict]:
        """Use ``/search/suggest.json`` for fast keyword search (max 10)."""
        url = f"{self.BASE_URL}/search/suggest.json"
        params = {
            "q": keyword,
            "resources[type]": "product",
            "resources[limit]": _SEARCH_SUGGEST_LIMIT,
            "resources[options][unavailable_products]": "last",
            "resources[options][fields]": (
                "title,product_type,variants.title,vendor,tag"
            ),
        }
        headers = self.build_headers()

        def _do_request() -> list[dict]:
            self.logger.info("[Suggest] Searching '%s' …", keyword)
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = self.safe_json(resp)

            products_raw = (
                data.get("resources", {}).get("results", {}).get("products", [])
            )
            if not products_raw:
                return []

            results: list[dict] = []
            for p in products_raw:
                handle = p.get("handle", "")
                prod_url = (
                    f"{self.BASE_URL}/products/{handle}"
                    if handle
                    else p.get("url", "")
                )
                if prod_url and not prod_url.startswith("http"):
                    prod_url = urljoin(self.BASE_URL, prod_url)

                price = self.parse_price(p.get("price"))
                compare_price = self.parse_price(
                    p.get("compare_at_price_max")
                )
                is_on_sale = compare_price > 0 and compare_price > price

                image_url = p.get("image", "")
                if isinstance(p.get("featured_image"), dict):
                    image_url = p["featured_image"].get("url", image_url)

                results.append(
                    {
                        "name": p.get("title", "N/A"),
                        "price": price,
                        "original_price": compare_price,
                        "is_on_sale": is_on_sale,
                        "store": self.NAME,
                        "brand": p.get("vendor", "N/A"),
                        "rating": 0.0,
                        "url": prod_url,
                        "image_url": image_url,
                        "is_ad": False,
                        "sold": "",
                        "reviews": 0,
                        "in_stock": p.get("available", False),
                        "sizes": [],
                        "colours": [],
                        "product_type": p.get("type", ""),
                        "tags": p.get("tags", []),
                    }
                )
            return results

        return self.retry(_do_request, label="Suggest")

    # ------------------------------------------------------------------
    # Strategy 2: Shopify Products JSON API
    # ------------------------------------------------------------------

    def _search_via_products_json(
        self, keyword: str, max_pages: int = 1
    ) -> list[dict]:
        """Fetch ``/products.json``, filter by *keyword* client-side."""
        headers = self.build_headers()
        all_results: list[dict] = []

        for page_num in range(1, max_pages + 1):
            if page_num > 1:
                self.random_delay()

            url = f"{self.BASE_URL}/products.json"
            params = {"limit": _PRODUCTS_PER_PAGE, "page": page_num}

            def _do_page_request(
                _url: str = url, _params: dict = params,
            ) -> list[dict]:
                self.logger.info("[JSON] Fetching page %d …", page_num)
                resp = requests.get(
                    _url, headers=headers, params=_params, timeout=20
                )
                resp.raise_for_status()
                return self.safe_json(resp).get("products", [])  # type: ignore[union-attr]

            try:
                products_raw = self.retry(
                    _do_page_request, label=f"JSON/p{page_num}"
                )
            except Exception:
                break

            if not products_raw:
                break

            matched = 0
            for product in products_raw:
                if self._keyword_matches(keyword, product):
                    normalised = self._normalise_product(product)
                    all_results.extend(normalised)
                    matched += 1

            self.logger.info(
                "[JSON] Page %d → %d/%d matched '%s'.",
                page_num, matched, len(products_raw), keyword,
            )

            if len(products_raw) < _PRODUCTS_PER_PAGE:
                break  # Last page reached.

        return all_results

    # ------------------------------------------------------------------
    # Strategy 3: Playwright fallback
    # ------------------------------------------------------------------

    def _search_via_playwright(self, keyword: str) -> list[dict]:
        """Headless browser fallback for blocked Shopify APIs."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.error(
                "Playwright is not installed.  "
                "Run: pip install playwright && python -m playwright install chromium"
            )
            return []

        search_url = (
            f"{self.BASE_URL}/search?q={quote_plus(keyword)}&type=product"
        )
        results: list[dict] = []

        self.logger.info("[Playwright] Launching headless browser …")

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
                page_obj.goto(
                    search_url, wait_until="domcontentloaded", timeout=45_000
                )
                try:
                    page_obj.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    pass

                for _ in range(4):
                    page_obj.evaluate("window.scrollBy(0, 800)")
                    page_obj.wait_for_timeout(random.randint(800, 1200))
                page_obj.wait_for_timeout(2000)

                content = page_obj.content()
                soup = BeautifulSoup(content, "lxml")

                results = self._extract_from_json_ld(soup)
                if not results:
                    results = self._extract_from_html(soup)

            except Exception as exc:
                self.logger.error("[Playwright] Error: %s", exc)
            finally:
                context.close()
                browser.close()

        return results

    # ------------------------------------------------------------------
    # Shopify-specific helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _keyword_matches(keyword: str, product: dict) -> bool:
        """Case-insensitive keyword match against product fields."""
        kw = keyword.lower()
        searchable = " ".join([
            product.get("title", ""),
            product.get("vendor", ""),
            product.get("product_type", ""),
            " ".join(product.get("tags", [])),
        ]).lower()
        return all(term in searchable for term in kw.split())

    def _normalise_product(self, product: dict) -> list[dict]:
        """Convert a Shopify product dict into a normalised product list."""
        variants = product.get("variants", [])
        if not variants:
            return []

        available = [v for v in variants if v.get("available", False)]
        price_source = available if available else variants

        prices = [self.parse_price(v.get("price")) for v in price_source]
        min_price = min(prices) if prices else 0

        compare_prices = [
            self.parse_price(v.get("compare_at_price"))
            for v in price_source
            if v.get("compare_at_price")
        ]
        original_price = min(compare_prices) if compare_prices else 0
        is_on_sale = original_price > 0 and original_price > min_price

        sizes: list[str] = []
        for v in variants:
            s = v.get("option1", "")
            if s and s not in sizes:
                sizes.append(s)

        colours: list[str] = []
        for v in variants:
            c = v.get("option2", "")
            if c and c not in colours:
                colours.append(c)

        handle = product.get("handle", "")
        url = f"{self.BASE_URL}/products/{handle}" if handle else ""

        images = product.get("images", [])
        image_url = images[0].get("src", "") if images else ""

        vendor = product.get("vendor", self.NAME)

        return [
            {
                "name": product.get("title", "N/A"),
                "price": min_price,
                "original_price": original_price,
                "is_on_sale": is_on_sale,
                "store": self.NAME,
                "brand": vendor,
                "rating": 0.0,
                "url": url,
                "image_url": image_url,
                "is_ad": False,
                "sold": "",
                "reviews": 0,
                "in_stock": len(available) > 0,
                "sizes": sizes,
                "colours": colours,
                "product_type": product.get("product_type", ""),
                "tags": product.get("tags", []),
            }
        ]

    def _extract_from_json_ld(self, soup: BeautifulSoup) -> list[dict]:
        """Extract products from JSON-LD ``<script>`` tags."""
        results: list[dict] = []
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
                if isinstance(data, dict) and data.get("@type") == "ItemList":
                    for item in data.get("itemListElement", []):
                        product = item.get("item", item)
                        price = self.parse_price(
                            product.get("offers", {}).get("price")
                        )
                        prod_url = product.get("url", "")
                        if prod_url and not prod_url.startswith("http"):
                            prod_url = urljoin(self.BASE_URL, prod_url)
                        results.append({
                            "name": product.get("name", "N/A"),
                            "price": price,
                            "original_price": 0,
                            "is_on_sale": False,
                            "store": self.NAME,
                            "brand": product.get("brand", {}).get("name", "N/A"),
                            "rating": self.parse_rating(
                                product.get("aggregateRating", {}).get("ratingValue")
                            ),
                            "url": prod_url,
                            "image_url": product.get("image", ""),
                            "is_ad": False,
                            "sold": "",
                            "reviews": 0,
                            "in_stock": True,
                            "sizes": [],
                            "colours": [],
                            "product_type": "",
                            "tags": [],
                        })
            except (json.JSONDecodeError, AttributeError):
                continue
        return results

    def _extract_from_html(self, soup: BeautifulSoup) -> list[dict]:
        """Parse product cards from rendered HTML (theme-agnostic)."""
        results: list[dict] = []
        selectors = [
            ".product-card", ".grid-product", ".product-item",
            "[data-product-card]", ".collection-product-card",
            ".card--product",
        ]
        cards: list = []
        for sel in selectors:
            cards = soup.select(sel)
            if cards:
                break

        for card in cards:
            name_el = (
                card.select_one(".product-card__title")
                or card.select_one(".grid-product__title")
                or card.select_one(".card__heading a")
                or card.select_one("h3 a")
                or card.select_one("h2 a")
            )
            name = name_el.get_text(strip=True) if name_el else "N/A"

            price_el = (
                card.select_one(".price-item--sale")
                or card.select_one(".product-card__price")
                or card.select_one(".price .money")
                or card.select_one(".price")
            )
            price = self.parse_price(
                price_el.get_text(strip=True) if price_el else None
            )

            link_el = card.select_one("a[href*='/products/']")
            raw_url = link_el.get("href", "") if link_el else ""
            prod_url = urljoin(self.BASE_URL, raw_url) if raw_url else ""

            vendor_el = (
                card.select_one(".product-card__vendor")
                or card.select_one(".grid-product__vendor")
            )
            vendor = vendor_el.get_text(strip=True) if vendor_el else "N/A"

            if name != "N/A" or price:
                results.append({
                    "name": name,
                    "price": price,
                    "original_price": 0,
                    "is_on_sale": False,
                    "store": self.NAME,
                    "brand": vendor,
                    "rating": 0.0,
                    "url": prod_url,
                    "image_url": "",
                    "is_ad": False,
                    "sold": "",
                    "reviews": 0,
                    "in_stock": True,
                    "sizes": [],
                    "colours": [],
                    "product_type": "",
                    "tags": [],
                })

        return results
