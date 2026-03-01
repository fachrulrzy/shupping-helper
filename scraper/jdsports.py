"""
JD Sports Indonesia (jdsports.id) Product Scraper
==================================================

Scrapes product data from `JD Sports Indonesia <https://www.jdsports.id>`_,
a custom JS-rendered e-commerce platform.

Since the site renders product data client-side, this scraper primarily uses
Playwright for reliable data extraction, with an HTML fallback for cases where
the initial page load contains product data.
"""

from __future__ import annotations

import random
import re
from typing import Any
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from scraper.base import BaseScraper
from scraper.registry import register


@register
class JDSportsScraper(BaseScraper):
    """Scraper for JD Sports Indonesia (jdsports.id).

    Uses two strategies:
    1. Playwright headless browser (primary — site is JS-rendered)
    2. Static HTML fallback
    """

    NAME = "JD Sports"
    SLUG = "jdsports"
    BASE_URL = "https://www.jdsports.id"

    # Search URL pattern: https://jdsports.id/search/{keyword}?page={n}
    SEARCH_URL = "https://jdsports.id/search"

    # Be polite — JD Sports can be slow to render.
    MIN_DELAY: float = 1.0
    MAX_DELAY: float = 2.5

    # ------------------------------------------------------------------
    # Public API — implements BaseScraper.search()
    # ------------------------------------------------------------------

    def search(self, keyword: str, max_pages: int = 1) -> list[dict]:
        """Search JD Sports Indonesia using Playwright with HTML fallback."""
        all_results: list[dict] = []

        for page_num in range(1, max_pages + 1):
            if page_num > 1:
                self.random_delay()

            products: list[dict] = []

            # ---- Strategy 1: Playwright (primary — site is JS-rendered) ----
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

            # ---- Strategy 2: Static HTML fallback ----
            if not products:
                self.logger.info("[HTML] Falling back to static scraping …")
                self.random_delay()
                try:
                    products = self._search_via_html(keyword, page=page_num)
                    if products:
                        self.logger.info(
                            "[HTML] Page %d → %d products.",
                            page_num, len(products),
                        )
                except Exception as exc:
                    self.logger.warning(
                        "[HTML] Failed for page %d: %s", page_num, exc
                    )

            if not products:
                self.logger.warning(
                    "No results for page %d. All strategies failed.", page_num
                )

            all_results.extend(products)

        # Deduplicate by URL.
        seen: set[str] = set()
        unique: list[dict] = []
        for p in all_results:
            url = p.get("url", "")
            if url and url not in seen:
                seen.add(url)
                unique.append(p)
            elif not url:
                unique.append(p)

        return unique

    # ------------------------------------------------------------------
    # Strategy 1: Playwright headless browser (primary)
    # ------------------------------------------------------------------

    def _search_via_playwright(self, keyword: str, page: int = 1) -> list[dict]:
        """Scrape JD Sports search using Playwright headless Chromium."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.error(
                "Playwright is not installed. "
                "Run: pip install playwright && python -m playwright install chromium"
            )
            return []

        url = f"{self.SEARCH_URL}/{quote_plus(keyword)}?page={page}"
        results: list[dict] = []

        self.logger.info(
            "[Playwright] Launching headless browser for page %d …", page
        )

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
                    page_obj.wait_for_load_state("networkidle", timeout=20_000)
                except Exception:
                    pass

                # Wait for product cards to render.
                try:
                    page_obj.wait_for_selector(
                        "a[href*='/product/'], [class*='product'], [class*='Product']",
                        timeout=10_000,
                    )
                except Exception:
                    self.logger.debug("[Playwright] No product selectors found.")

                # Scroll to load lazy content.
                for _ in range(5):
                    page_obj.evaluate("window.scrollBy(0, 800)")
                    page_obj.wait_for_timeout(random.randint(800, 1500))
                page_obj.wait_for_timeout(2000)

                content = page_obj.content()
                soup = BeautifulSoup(content, "lxml")

                results = self._parse_product_cards(soup)

                # Fallback: try extracting from __NEXT_DATA__ or script tags.
                if not results:
                    results = self._extract_from_scripts(soup)

            except Exception as exc:
                self.logger.error("[Playwright] Error: %s", exc)
            finally:
                context.close()
                browser.close()

        return results

    # ------------------------------------------------------------------
    # Strategy 2: Static HTML fallback
    # ------------------------------------------------------------------

    def _search_via_html(self, keyword: str, page: int = 1) -> list[dict]:
        """Try scraping via static requests (unlikely to work for JS sites)."""
        url = f"{self.SEARCH_URL}/{quote_plus(keyword)}?page={page}"
        headers = self.build_headers()
        headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        )

        try:
            self.logger.info("[HTML] Requesting '%s' …", url)
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "lxml")

            # Try __NEXT_DATA__ first (Next.js server-side data).
            results = self._extract_from_scripts(soup)
            if results:
                return results

            # Try HTML product cards.
            return self._parse_product_cards(soup)

        except requests.RequestException as exc:
            self.logger.warning("[HTML] Failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_product_cards(self, soup: BeautifulSoup) -> list[dict]:
        """Parse product cards from JD Sports DOM.

        JD Sports renders product info as concatenated text inside ``<a>``
        links, e.g. ``"adidas Originals Samba OGRp 2.200.000(5/5)"``.
        We regex-split name, price, and rating from the combined text.
        """
        results: list[dict] = []

        # JD Sports uses <a> tags linking to /product/ for each item.
        product_links = soup.select("a[href*='/product/']")
        self.logger.debug("Found %d product link candidates.", len(product_links))

        seen_urls: set[str] = set()

        for link in product_links:
            try:
                href = link.get("href", "")
                if not href or "/product/" not in href:
                    continue

                full_url = urljoin(self.BASE_URL, href)
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                # Get the full text of the link (name + price + rating
                # are concatenated together in JD Sports).
                raw_text = link.get_text(strip=True)
                if not raw_text or len(raw_text) < 5:
                    continue

                # ---- Split name / price / rating using regex ----
                # Pattern: "Product NameRp 2.200.000(5/5)" or just
                #          "Product NameRp 2.200.000"
                price_match = re.search(
                    r"(Rp[\s\xa0]*[\d.,]+)", raw_text, re.IGNORECASE
                )
                if price_match:
                    name = raw_text[: price_match.start()].strip()
                    price = self.parse_price(price_match.group(1))
                else:
                    name = raw_text
                    price = 0

                # Remove trailing rating like "(5/5)" or "(4.8/5)" from name.
                name = re.sub(r"\(\d+\.?\d*/\d+\)\s*$", "", name).strip()

                if not name or len(name) < 3:
                    continue

                # ---- Rating ----
                rating = 0.0
                rating_match = re.search(r"\((\d+\.?\d*)/5\)", raw_text)
                if rating_match:
                    rating = self.parse_rating(rating_match.group(1))

                # ---- Walk up ONE level only for image/sale info ----
                card = link.parent or link

                # ---- Original price (sale detection) ----
                original_price = 0
                old_els = card.select("s, del, strike, [class*='was']")
                for el in old_els:
                    parsed = self.parse_price(el.get_text(strip=True))
                    if parsed > price:
                        original_price = parsed
                        break
                is_on_sale = original_price > 0 and original_price > price

                # ---- Brand ----
                brand = self._infer_brand(name)

                # ---- Image ----
                img_el = card.select_one("img")
                image_url = ""
                if img_el:
                    image_url = (
                        img_el.get("src")
                        or img_el.get("data-src")
                        or ""
                    )

                results.append({
                    "name": name,
                    "price": price,
                    "original_price": original_price,
                    "is_on_sale": is_on_sale,
                    "store": self.NAME,
                    "brand": brand,
                    "rating": rating,
                    "url": full_url,
                    "image_url": image_url,
                    "is_ad": False,
                    "sold": "",
                    "reviews": 0,
                    "in_stock": True,
                })

            except Exception as exc:
                self.logger.debug("Skipping product link: %s", exc)
                continue

        return results

    def _extract_from_scripts(self, soup: BeautifulSoup) -> list[dict]:
        """Try to extract product data from embedded script tags.

        Many JS-rendered sites embed initial data in __NEXT_DATA__
        or similar script tags.
        """
        import json

        results: list[dict] = []

        # Look for __NEXT_DATA__ (Next.js).
        next_data = soup.select_one("script#__NEXT_DATA__")
        if next_data and next_data.string:
            try:
                data = json.loads(next_data.string)
                products = self._dig_for_products(data)
                for p in products:
                    name = p.get("name") or p.get("title") or ""
                    if not name:
                        continue
                    price = self.parse_price(
                        p.get("price") or p.get("salePrice") or
                        p.get("currentPrice") or 0
                    )
                    original = self.parse_price(
                        p.get("originalPrice") or p.get("wasPrice") or
                        p.get("retailPrice") or 0
                    )
                    url_path = (
                        p.get("url") or p.get("href") or
                        p.get("slug") or p.get("seoUrl") or ""
                    )
                    if url_path and not url_path.startswith("http"):
                        url_path = urljoin(self.BASE_URL, url_path)

                    results.append({
                        "name": name,
                        "price": price,
                        "original_price": original,
                        "is_on_sale": original > 0 and original > price,
                        "store": self.NAME,
                        "brand": p.get("brand", self._infer_brand(name)),
                        "rating": 0.0,
                        "url": url_path,
                        "image_url": p.get("image", ""),
                        "is_ad": False,
                        "sold": "",
                        "reviews": 0,
                        "in_stock": p.get("inStock", True),
                    })
            except (json.JSONDecodeError, AttributeError) as exc:
                self.logger.debug("Failed to parse __NEXT_DATA__: %s", exc)

        # Look for JSON-LD.
        if not results:
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                    if isinstance(data, dict) and data.get("@type") == "ItemList":
                        for item in data.get("itemListElement", []):
                            product = item.get("item", item)
                            name = product.get("name", "")
                            if not name:
                                continue
                            price = self.parse_price(
                                product.get("offers", {}).get("price")
                            )
                            prod_url = product.get("url", "")
                            if prod_url and not prod_url.startswith("http"):
                                prod_url = urljoin(self.BASE_URL, prod_url)
                            results.append({
                                "name": name,
                                "price": price,
                                "original_price": 0,
                                "is_on_sale": False,
                                "store": self.NAME,
                                "brand": product.get("brand", {}).get(
                                    "name", self._infer_brand(name)
                                ),
                                "rating": 0.0,
                                "url": prod_url,
                                "image_url": product.get("image", ""),
                                "is_ad": False,
                                "sold": "",
                                "reviews": 0,
                                "in_stock": True,
                            })
                except (json.JSONDecodeError, AttributeError):
                    continue

        return results

    def _dig_for_products(self, data: Any, depth: int = 0) -> list[dict]:
        """Recursively search a JSON structure for product-like objects."""
        if depth > 8:
            return []

        products: list[dict] = []

        if isinstance(data, dict):
            # Check if this dict looks like a product.
            if ("name" in data or "title" in data) and (
                "price" in data
                or "salePrice" in data
                or "currentPrice" in data
            ):
                products.append(data)
            else:
                for key, value in data.items():
                    if key in ("products", "items", "results", "searchResults"):
                        if isinstance(value, list):
                            for item in value:
                                if isinstance(item, dict):
                                    products.append(item)
                        continue
                    products.extend(self._dig_for_products(value, depth + 1))
        elif isinstance(data, list):
            for item in data:
                products.extend(self._dig_for_products(item, depth + 1))

        return products

    @staticmethod
    def _infer_brand(product_name: str) -> str:
        """Try to infer the brand from the product name."""
        known_brands = [
            "adidas Originals", "adidas",
            "Nike", "New Balance", "Puma", "Converse", "Reebok",
            "Vans", "ASICS", "Under Armour", "The North Face",
            "Jordan", "Lacoste", "Crocs", "Timberland", "Fila",
            "Skechers", "Hoka", "On Running", "Salomon",
        ]
        name_lower = product_name.lower()
        for brand in known_brands:
            if name_lower.startswith(brand.lower()):
                return brand
        return "N/A"


# ---------------------------------------------------------------------------
# Backward-compatible module-level functions
# ---------------------------------------------------------------------------

_instance = JDSportsScraper()


def search_jdsports(keyword: str, max_pages: int = 1) -> list[dict]:
    """Search JD Sports Indonesia — delegates to :class:`JDSportsScraper`."""
    return _instance.search(keyword, max_pages=max_pages)


def export_to_csv(products: list[dict], filepath: str) -> "Path":  # noqa: F821
    """Export to CSV — delegates to :class:`JDSportsScraper`."""
    return _instance.export_to_csv(products, filepath)