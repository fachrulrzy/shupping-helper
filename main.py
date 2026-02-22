#!/usr/bin/env python3
"""
Smart Price Comparison Tool – Phase 1: Tokopedia Scraper
=========================================================

Usage
-----
    python main.py "adidas samba"
    python main.py "adidas samba" --pages 2
    python main.py "adidas samba" --pages 2 --export results.csv
    python main.py "adidas samba" --verbose

"""

from __future__ import annotations

import argparse
import logging
import sys
import textwrap

from scraper.tokopedia import export_to_csv, search_tokopedia

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_price(price: int) -> str:
    """Format an integer price into Indonesian Rupiah notation.

    >>> _format_price(1450000)
    'Rp 1.450.000'
    """
    if not price:
        return "N/A"
    formatted = f"{price:,}".replace(",", ".")
    return f"Rp {formatted}"


def _truncate(text: str, width: int = 80) -> str:
    """Truncate a string to *width* characters, adding '…' if needed."""
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def print_results(keyword: str, products: list[dict]) -> None:
    """Pretty-print the product list to the terminal."""

    separator = "─" * 60

    print(f"\n{'═' * 60}")
    print(f"  🔍  Searching: {keyword}")
    print(f"{'═' * 60}\n")

    if not products:
        print("  ⚠  No results found. Tokopedia may be blocking requests.")
        print("     Try again later or install Playwright for browser-based scraping:")
        print("       pip install playwright && python -m playwright install chromium\n")
        return

    print(f"  Tokopedia Results ({len(products)} products):\n")

    for idx, product in enumerate(products, start=1):
        ad_tag = " [AD]" if product.get("is_ad") else ""
        rating_str = f"{product['rating']:.1f}" if product["rating"] else "N/A"
        sold_str = f"  |  Sold: {product['sold']}" if product.get("sold") else ""
        review_str = f"  |  Reviews: {product['reviews']}" if product.get("reviews") else ""

        print(f"  {idx}. {_truncate(product['name'])}{ad_tag}")
        print(f"     Price  : {_format_price(product['price'])}")
        print(f"     Store  : {product['store']}")
        print(f"     Rating : ⭐ {rating_str}{sold_str}{review_str}")
        print(f"     Link   : {_truncate(product['url'], 100)}")
        print(f"     {separator}")

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Create and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="shupping-helper",
        description=textwrap.dedent("""\
            Smart Price Comparison Tool – Phase 1
            Scrape product data from Tokopedia and display structured results.
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "keyword",
        type=str,
        help='Product search keyword, e.g. "adidas samba"',
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        help="Number of search result pages to scrape (default: 1)",
    )
    parser.add_argument(
        "--export",
        type=str,
        default=None,
        metavar="FILE",
        help="Export results to a CSV file (e.g. results.csv)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # Configure logging.
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    keyword: str = args.keyword.strip()
    if not keyword:
        parser.error("Please provide a non-empty search keyword.")

    # ---- Scrape ----
    try:
        products = search_tokopedia(keyword, max_pages=args.pages)
    except KeyboardInterrupt:
        print("\n  ⏹  Interrupted by user.")
        return 130
    except Exception as exc:
        logging.error("Fatal error during scraping: %s", exc)
        return 1

    # ---- Display ----
    print_results(keyword, products)

    # ---- Optional export ----
    if args.export:
        try:
            out = export_to_csv(products, args.export)
            print(f"  📁  Results exported to: {out}\n")
        except Exception as exc:
            logging.error("Failed to export CSV: %s", exc)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
