"""
Tokopedia Product Scraper Module

Provides functionality to search and scrape product data from Tokopedia.
Supports both static (requests + BS4) and dynamic (Playwright) scraping strategies.
Falls back to Playwright automatically if static scraping is blocked.
"""

from __future__ import annotations

import csv
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.tokopedia.com"
SEARCH_URL = f"{BASE_URL}/search"

# Tokopedia uses a GraphQL API internally – we can query it directly for
# much more reliable results than scraping rendered HTML.
GQL_URL = "https://gql.tokopedia.com/graphql/SearchProductQueryV4"

# Delays (seconds) between consecutive requests to avoid rate-limiting.
MIN_DELAY: float = 1.5
MAX_DELAY: float = 3.0

MAX_RETRIES: int = 3
RETRY_BACKOFF: float = 2.0  # exponential back-off multiplier

PRODUCTS_PER_PAGE: int = 60  # Tokopedia default page size

ua = UserAgent(fallback="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _random_delay() -> None:
    """Sleep for a random interval between MIN_DELAY and MAX_DELAY."""
    delay = random.uniform(MIN_DELAY, MAX_DELAY)
    logger.debug("Sleeping %.2f s …", delay)
    time.sleep(delay)


def _build_headers() -> dict[str, str]:
    """Return realistic browser-like HTTP headers with a rotated User-Agent."""
    return {
        "User-Agent": ua.random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": BASE_URL,
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }


def _build_gql_headers() -> dict[str, str]:
    """Headers specifically for the Tokopedia internal GraphQL endpoint."""
    headers = _build_headers()
    headers.update({
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/search",
        "X-Source": "tokopedia-lite",
        "X-Tkpd-Lite-Service": "zeus",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    })
    return headers


def _parse_price(raw: str | int | None) -> int:
    """Convert various price representations to a plain integer.

    Examples
    --------
    >>> _parse_price("Rp 1.450.000")
    1450000
    >>> _parse_price("Rp1,390,000")
    1390000
    >>> _parse_price(1450000)
    1450000
    """
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    cleaned = re.sub(r"[^\d]", "", str(raw))
    return int(cleaned) if cleaned else 0


def _parse_rating(raw: Any) -> float:
    """Safely parse a rating value to float, defaulting to 0.0."""
    if raw is None:
        return 0.0
    try:
        return round(float(raw), 1)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# Strategy 1: GraphQL API (most reliable)
# ---------------------------------------------------------------------------


def _build_gql_payload(keyword: str, page: int = 1) -> list[dict]:
    """Construct the GraphQL request body for Tokopedia product search."""
    variables = {
        "params": (
            f"device=desktop&navsource=&ob=23&page={page}"
            f"&q={quote_plus(keyword)}&related=true"
            f"&rows={PRODUCTS_PER_PAGE}&safe_search=false"
            f"&scheme=https&shipping=&show_adult=false"
            f"&source=search&srp_component_id=02.01.00.00"
            f"&srp_page_id=&srp_page_title=&st=product"
            f"&start={(page - 1) * PRODUCTS_PER_PAGE}"
            f"&topads_bucket=true&unique_id=&user_addressId="
            f"&user_cityId=&user_districtId=&user_id="
            f"&user_lat=&user_long=&user_postCode=&user_warehouseId="
            f"&variants=&warehouses="
        )
    }

    return [
        {
            "operationName": "SearchProductQueryV4",
            "variables": variables,
            "query": (
                "query SearchProductQueryV4($params: String!) {\n"
                "  ace_search_product_v4(params: $params) {\n"
                "    header {\n"
                "      totalData\n"
                "      totalDataText\n"
                "      responseCode\n"
                "      keywordProcess\n"
                "    }\n"
                "    data {\n"
                "      products {\n"
                "        id\n"
                "        name\n"
                "        url\n"
                "        imageUrl\n"
                "        price\n"
                "        priceInt\n"
                "        shop {\n"
                "          id\n"
                "          name\n"
                "          url\n"
                "          city\n"
                "          isOfficial\n"
                "          isPowerBadge\n"
                "        }\n"
                "        rating\n"
                "        ratingAverage\n"
                "        countReview\n"
                "        countSold\n"
                "        labels {\n"
                "          title\n"
                "          color\n"
                "        }\n"
                "        badges {\n"
                "          title\n"
                "          imageUrl\n"
                "        }\n"
                "        ads {\n"
                "          id\n"
                "        }\n"
                "      }\n"
                "    }\n"
                "  }\n"
                "}\n"
            ),
        }
    ]


def _search_via_gql(keyword: str, page: int = 1) -> list[dict]:
    """Fetch product data using Tokopedia's internal GraphQL endpoint.

    Returns a list of normalised product dictionaries.
    """
    payload = _build_gql_payload(keyword, page)
    headers = _build_gql_headers()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("[GQL] Requesting page %d (attempt %d) …", page, attempt)
            resp = requests.post(
                GQL_URL,
                headers=headers,
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            # The response is a list; the first element holds our query data.
            first = data[0] if isinstance(data, list) and data else data
            ace_data = (first or {}).get("data")
            if ace_data is None:
                logger.warning("[GQL] Response contained no data (possibly blocked or schema changed).")
                return []

            products_raw = (
                ace_data
                .get("ace_search_product_v4", {})
                .get("data", {})
                .get("products", [])
            )

            results: list[dict] = []
            for p in products_raw:
                # Skip sponsored / TopAds products if they have an ads block.
                is_ad = bool(p.get("ads", {}).get("id"))
                results.append(
                    {
                        "name": p.get("name", "N/A"),
                        "price": _parse_price(p.get("priceInt") or p.get("price")),
                        "store": p.get("shop", {}).get("name", "N/A"),
                        "rating": _parse_rating(p.get("ratingAverage") or p.get("rating")),
                        "url": p.get("url", ""),
                        "is_ad": is_ad,
                        "sold": p.get("countSold", ""),
                        "reviews": p.get("countReview", 0),
                    }
                )
            return results

        except requests.RequestException as exc:
            logger.warning("[GQL] Attempt %d failed: %s", attempt, exc)
            if attempt < MAX_RETRIES:
                backoff = RETRY_BACKOFF ** attempt + random.uniform(0, 1)
                logger.info("[GQL] Retrying in %.1f s …", backoff)
                time.sleep(backoff)
            else:
                logger.error("[GQL] All %d attempts exhausted.", MAX_RETRIES)
                raise

    return []


# ---------------------------------------------------------------------------
# Strategy 2: Static HTML scraping (fallback)
# ---------------------------------------------------------------------------


def _search_via_html(keyword: str, page: int = 1) -> list[dict]:
    """Scrape Tokopedia search results via static HTML with BeautifulSoup.

    This strategy works when the page is server-side rendered. It may
    return empty results if Tokopedia blocks the request or serves a
    JS-only page.
    """
    params = {"q": keyword, "page": page}
    headers = _build_headers()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("[HTML] Requesting page %d (attempt %d) …", page, attempt)
            resp = requests.get(SEARCH_URL, headers=headers, params=params, timeout=15)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "lxml")

            # Try to find JSON-LD or inline data first (more reliable).
            results = _extract_from_json_ld(soup)
            if results:
                return results

            # Fall back to parsing product cards from the DOM.
            results = _extract_from_dom(soup)
            return results

        except requests.RequestException as exc:
            logger.warning("[HTML] Attempt %d failed: %s", attempt, exc)
            if attempt < MAX_RETRIES:
                backoff = RETRY_BACKOFF ** attempt + random.uniform(0, 1)
                time.sleep(backoff)
            else:
                raise

    return []


def _extract_from_json_ld(soup: BeautifulSoup) -> list[dict]:
    """Try to pull product data from embedded JSON-LD scripts."""
    results: list[dict] = []
    for script_tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script_tag.string or "")
            if isinstance(data, dict) and data.get("@type") == "ItemList":
                for item in data.get("itemListElement", []):
                    product = item.get("item", item)
                    results.append(
                        {
                            "name": product.get("name", "N/A"),
                            "price": _parse_price(
                                product.get("offers", {}).get("price")
                            ),
                            "store": product.get("brand", {}).get("name", "N/A"),
                            "rating": _parse_rating(
                                product.get("aggregateRating", {}).get("ratingValue")
                            ),
                            "url": product.get("url", ""),
                            "is_ad": False,
                            "sold": "",
                            "reviews": 0,
                        }
                    )
        except (json.JSONDecodeError, AttributeError):
            continue
    return results


def _extract_from_dom(soup: BeautifulSoup) -> list[dict]:
    """Parse product cards directly from the DOM tree."""
    results: list[dict] = []

    # Tokopedia product cards are rendered inside data-testid containers.
    # Selectors may change over time; these cover common patterns.
    selectors = [
        "[data-testid='divProductWrapper']",
        "[data-testid='lstCL2ProductList'] > div",
        ".css-bk6tzz",  # legacy class-based selector
        "[data-testid='spnSRPProdName']",
    ]

    cards = []
    for sel in selectors:
        cards = soup.select(sel)
        if cards:
            break

    for card in cards:
        name_el = (
            card.select_one("[data-testid='spnSRPProdName']")
            or card.select_one("[data-testid='linkProductName']")
            or card.select_one("span.css-20kt3o")
            or card.select_one("a span")
        )
        price_el = (
            card.select_one("[data-testid='spnSRPProdPrice']")
            or card.select_one("span.css-o5uqvq")
            or card.select_one("[data-testid='linkProductPrice']")
        )
        store_el = (
            card.select_one("[data-testid='spnSRPProdShop']")
            or card.select_one("span.css-1kr22w3")
        )
        rating_el = (
            card.select_one("[data-testid='spnSRPProdReview']")
            or card.select_one("span.css-153qjw7")
        )
        link_el = card.select_one("a[href*='/']")

        name = name_el.get_text(strip=True) if name_el else "N/A"
        price = _parse_price(price_el.get_text(strip=True) if price_el else None)
        store = store_el.get_text(strip=True) if store_el else "N/A"
        rating = _parse_rating(rating_el.get_text(strip=True) if rating_el else None)
        url_raw = link_el.get("href", "") if link_el else ""
        url = urljoin(BASE_URL, url_raw) if url_raw else ""

        if name != "N/A" or price:
            results.append(
                {
                    "name": name,
                    "price": price,
                    "store": store,
                    "rating": rating,
                    "url": url,
                    "is_ad": False,
                    "sold": "",
                    "reviews": 0,
                }
            )

    return results


# ---------------------------------------------------------------------------
# Strategy 3: Playwright headless browser (ultimate fallback)
# ---------------------------------------------------------------------------


def _search_via_playwright(keyword: str, page: int = 1) -> list[dict]:
    """Scrape Tokopedia search using Playwright headless Chromium.

    This is the most robust strategy but the slowest. It is used when
    both the GraphQL and static HTML approaches fail.

    It intercepts the internal GraphQL network calls that Tokopedia's
    frontend makes, giving us clean structured JSON data.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error(
            "Playwright is not installed. "
            "Run: pip install playwright && python -m playwright install chromium"
        )
        return []

    url = f"{SEARCH_URL}?q={quote_plus(keyword)}&page={page}"
    results: list[dict] = []
    captured_responses: list[dict] = []

    def _handle_response(response):
        """Capture GraphQL responses containing search product data."""
        try:
            req_url = response.url
            if "gql.tokopedia.com" in req_url and response.status == 200:
                body = response.json()
                # The response can be a list of query results
                items = body if isinstance(body, list) else [body]
                for item in items:
                    data = item.get("data", {})
                    if data is None:
                        continue
                    # Scan all top-level keys for product lists.
                    for key, node in data.items():
                        if not isinstance(node, dict):
                            continue
                        # V5 structure: data.{key}.data.products
                        products = (
                            node.get("data", {}).get("products", [])
                            if isinstance(node.get("data"), dict) else []
                        )
                        # V4 fallback: data.{key}.products
                        if not products:
                            products = node.get("products", [])
                        if products and isinstance(products, list):
                            captured_responses.extend(products)
        except Exception:
            pass  # Non-JSON or irrelevant response

    logger.info("[Playwright] Launching headless browser for page %d …", page)

    with sync_playwright() as pw:
        # Use the real Chrome channel if available — much harder for sites to detect.
        launch_kwargs: dict[str, Any] = {"headless": True}
        used_chrome = False
        try:
            browser = pw.chromium.launch(channel="chrome", **launch_kwargs)
            used_chrome = True
        except Exception:
            browser = pw.chromium.launch(**launch_kwargs)

        context = browser.new_context(
            user_agent=ua.random,
            viewport={"width": 1366, "height": 768},
            locale="id-ID",
            java_script_enabled=True,
            bypass_csp=True,
            extra_http_headers={
                "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
                "sec-ch-ua": '"Google Chrome";v="124", "Chromium";v="124", "Not-A.Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            },
        )

        page_obj = context.new_page()
        page_obj.on("response", _handle_response)

        # Only apply stealth when NOT using real Chrome (it can interfere
        # with network interception and is unnecessary with real Chrome).
        if not used_chrome:
            try:
                from playwright_stealth import Stealth
                Stealth().apply_stealth_sync(page_obj)
                logger.debug("[Playwright] Stealth patches applied.")
            except (ImportError, Exception) as exc:
                logger.debug("[Playwright] Stealth not available: %s", exc)

        try:
            page_obj.goto(url, wait_until="domcontentloaded", timeout=45_000)

            # Wait for product content to render (network-idle or timeout).
            try:
                page_obj.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass

            # Scroll down gradually to trigger lazy-loading.
            for _ in range(6):
                page_obj.evaluate("window.scrollBy(0, 800)")
                page_obj.wait_for_timeout(random.randint(800, 1500))

            # Give remaining network calls a moment to complete.
            page_obj.wait_for_timeout(3000)

            # ---- Strategy A: Use intercepted GraphQL data ----
            if captured_responses:
                logger.info(
                    "[Playwright] Captured %d products from network.",
                    len(captured_responses),
                )
                for p in captured_responses:
                    # Handle V5 price structure: price can be a dict with
                    # {"text": "Rp2.100.000", "number": 2100000, ...}
                    # or V4 legacy: price is a string, priceInt is an int.
                    raw_price = p.get("price")
                    if isinstance(raw_price, dict):
                        price_val = raw_price.get("number") or _parse_price(raw_price.get("text"))
                    else:
                        price_val = _parse_price(p.get("priceInt") or raw_price)

                    # Shop can be a dict in both V4 and V5.
                    shop_data = p.get("shop") or {}
                    store_name = shop_data.get("name", "N/A") if isinstance(shop_data, dict) else "N/A"

                    # Rating is a string in V5 ("4.9"), float/int in V4.
                    rating_val = _parse_rating(
                        p.get("ratingAverage") or p.get("rating")
                    )

                    # Ads detection: V5 has ads.id as empty string for non-ads.
                    ads_data = p.get("ads") or {}
                    is_ad = bool(ads_data.get("id")) if isinstance(ads_data, dict) else False

                    # Sold count from labelGroups (V5) or countSold (V4).
                    sold = p.get("countSold", "")
                    if not sold:
                        for lg in (p.get("labelGroups") or []):
                            if lg.get("position") == "ri_product_credibility":
                                sold = lg.get("title", "")
                                break

                    results.append(
                        {
                            "name": p.get("name", "N/A"),
                            "price": int(price_val) if price_val else 0,
                            "store": store_name,
                            "rating": rating_val,
                            "url": p.get("url", ""),
                            "is_ad": is_ad,
                            "sold": sold,
                            "reviews": p.get("countReview", 0),
                        }
                    )

            # ---- Strategy B: Parse the rendered DOM ----
            if not results:
                content = page_obj.content()
                soup = BeautifulSoup(content, "lxml")
                results = _extract_from_json_ld(soup)
                if not results:
                    results = _extract_from_dom(soup)

            # ---- Strategy C: Playwright locators ----
            if not results:
                results = _extract_via_playwright_locators(page_obj)

        except Exception as exc:
            logger.error("[Playwright] Error: %s", exc)
        finally:
            context.close()
            browser.close()

    return results


def _extract_via_playwright_locators(page_obj: Any) -> list[dict]:
    """Use Playwright locators to extract product data from the live page."""
    results: list[dict] = []

    product_cards = page_obj.locator(
        "[data-testid='divProductWrapper'], "
        "[data-testid='lstCL2ProductList'] > div"
    )
    count = product_cards.count()
    logger.info("[Playwright] Found %d product cards via locators.", count)

    for i in range(count):
        card = product_cards.nth(i)
        try:
            name_loc = card.locator(
                "[data-testid='spnSRPProdName'], "
                "[data-testid='linkProductName']"
            )
            name = name_loc.first.inner_text(timeout=2000) if name_loc.count() else "N/A"

            price_loc = card.locator(
                "[data-testid='spnSRPProdPrice'], "
                "[data-testid='linkProductPrice']"
            )
            price_text = price_loc.first.inner_text(timeout=2000) if price_loc.count() else "0"

            store_loc = card.locator("[data-testid='spnSRPProdShop']")
            store = store_loc.first.inner_text(timeout=2000) if store_loc.count() else "N/A"

            rating_loc = card.locator("[data-testid='spnSRPProdReview']")
            rating_text = rating_loc.first.inner_text(timeout=2000) if rating_loc.count() else "0"

            link_loc = card.locator("a").first
            url = link_loc.get_attribute("href", timeout=2000) or ""
            if url and not url.startswith("http"):
                url = urljoin(BASE_URL, url)

            results.append(
                {
                    "name": name.strip(),
                    "price": _parse_price(price_text),
                    "store": store.strip(),
                    "rating": _parse_rating(rating_text),
                    "url": url,
                    "is_ad": False,
                    "sold": "",
                    "reviews": 0,
                }
            )
        except Exception as exc:
            logger.debug("[Playwright] Skipping card %d: %s", i, exc)
            continue

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_tokopedia(keyword: str, max_pages: int = 1) -> list[dict]:
    """Search Tokopedia for *keyword* and return structured product data.

    Tries three strategies in order:
    1. Internal GraphQL API (fastest, most structured)
    2. Static HTML scraping (requests + BS4)
    3. Playwright headless browser (slowest but most robust)

    Parameters
    ----------
    keyword : str
        The product search term (e.g. ``"adidas samba"``).
    max_pages : int, optional
        Number of search-result pages to scrape (default ``1``).

    Returns
    -------
    list[dict]
        Each dict has keys: ``name``, ``price``, ``store``, ``rating``, ``url``.
        ``price`` is an ``int`` (IDR), ``rating`` is a ``float``.
    """
    all_results: list[dict] = []

    for page_num in range(1, max_pages + 1):
        if page_num > 1:
            _random_delay()

        products: list[dict] = []

        # ---- Strategy 1: GraphQL ----
        try:
            products = _search_via_gql(keyword, page=page_num)
            if products:
                logger.info(
                    "[GQL] Page %d → %d products.", page_num, len(products)
                )
        except Exception as exc:
            logger.warning("[GQL] Failed for page %d: %s", page_num, exc)

        # ---- Strategy 2: Static HTML ----
        if not products:
            logger.info("[HTML] Falling back to static scraping …")
            _random_delay()
            try:
                products = _search_via_html(keyword, page=page_num)
                if products:
                    logger.info(
                        "[HTML] Page %d → %d products.", page_num, len(products)
                    )
            except Exception as exc:
                logger.warning("[HTML] Failed for page %d: %s", page_num, exc)

        # ---- Strategy 3: Playwright ----
        if not products:
            logger.info("[Playwright] Falling back to headless browser …")
            _random_delay()
            try:
                products = _search_via_playwright(keyword, page=page_num)
                if products:
                    logger.info(
                        "[Playwright] Page %d → %d products.",
                        page_num,
                        len(products),
                    )
            except Exception as exc:
                logger.warning(
                    "[Playwright] Failed for page %d: %s", page_num, exc
                )

        if not products:
            logger.warning(
                "No results obtained for page %d. All strategies failed.", page_num
            )

        all_results.extend(products)

    return all_results


# ---------------------------------------------------------------------------
# CSV Export Helper
# ---------------------------------------------------------------------------


def export_to_csv(products: list[dict], filepath: str | Path) -> Path:
    """Export a list of product dicts to a CSV file.

    Parameters
    ----------
    products : list[dict]
        Product data as returned by :func:`search_tokopedia`.
    filepath : str or Path
        Destination file path.

    Returns
    -------
    Path
        The resolved path of the written file.
    """
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["name", "price", "store", "rating", "url", "is_ad", "sold", "reviews"]
    with open(filepath, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(products)

    logger.info("Exported %d products → %s", len(products), filepath)
    return filepath.resolve()
