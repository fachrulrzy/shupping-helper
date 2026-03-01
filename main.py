#!/usr/bin/env python3
"""
Smart Price Comparison Tool – Multi-Source Scraper
===================================================

Usage
-----
    python main.py "adidas samba"
    python main.py "adidas samba" --source seek
    python main.py "adidas samba" --source odd
    python main.py "adidas samba" --source all
    python main.py "adidas samba" --pages 2
    python main.py "adidas samba" --pages 2 --export results.csv
    python main.py "adidas samba" --verbose

"""

from __future__ import annotations

import argparse
import logging
import sys
import textwrap

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Importing the package registers all scrapers.
import scraper  # noqa: F401
from scraper.registry import get_scraper, list_sources, list_scrapers

console = Console()

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_price(price: int) -> str:
    """Format an integer price into Indonesian Rupiah notation."""
    if not price:
        return "N/A"
    formatted = f"{price:,}".replace(",", ".")
    return f"Rp {formatted}"


def _truncate(text: str, width: int = 50) -> str:
    """Truncate a string to *width* characters, adding '…' if needed."""
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _make_price_text(product: dict, cheapest: int) -> Text:
    """Build a Rich Text object for the price with color coding."""
    price = product["price"]
    text = Text()

    # Color code: green for cheapest, yellow for mid, white for normal.
    if price == cheapest and cheapest > 0:
        text.append(_format_price(price), style="bold green")
        text.append(" 🏆", style="bold")
    else:
        text.append(_format_price(price), style="bold white")

    # Sale badge.
    if product.get("is_on_sale") and product.get("original_price"):
        orig = product["original_price"]
        discount = round((1 - price / orig) * 100) if orig > 0 else 0
        text.append(f"  was {_format_price(orig)}", style="dim")
        text.append(f"  -{discount}%", style="bold red")

    return text


def _make_source_text(product: dict) -> Text:
    """Color-code the source label."""
    source = product.get("_source") or product.get("store", "")
    text = Text()
    if "Seek" in source:
        text.append(source, style="cyan")
    elif "Daily Dose" in source or "ODD" in source.upper():
        text.append(source, style="magenta")
    else:
        text.append(source, style="yellow")
    return text


def print_results(
    keyword: str,
    products: list[dict],
    source_label: str = "Our Daily Dose",
) -> None:
    """Pretty-print the product list using Rich tables."""

    # ---- Header ----
    console.print()
    console.print(
        Panel(
            f"[bold white]🔍 Searching:[/] [cyan]{keyword}[/]  •  "
            f"[bold]{source_label}[/]  •  "
            f"[green]{len(products)} products found[/]",
            border_style="blue",
            padding=(0, 2),
        )
    )

    if not products:
        console.print(
            Panel(
                "[yellow]⚠ No results found.[/]\n"
                "Try again later or install Playwright:\n"
                "[dim]pip install playwright && python -m playwright install chromium[/dim]",
                border_style="yellow",
            )
        )
        return

    # ---- Find cheapest for highlighting ----
    prices = [p["price"] for p in products if p["price"] > 0]
    cheapest = min(prices) if prices else 0

    # ---- Product table ----
    table = Table(
        show_header=True,
        header_style="bold bright_white on #1a1a2e",
        border_style="bright_black",
        row_styles=["", "on #0d0d1a"],
        pad_edge=True,
        expand=True,
    )

    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Product", min_width=35, ratio=3)
    table.add_column("Price", min_width=18, justify="right")
    table.add_column("Source", min_width=16)
    table.add_column("Brand", min_width=10)
    table.add_column("Status", min_width=8, justify="center")

    for idx, product in enumerate(products, start=1):
        # Name + link underneath.
        name = _truncate(product["name"], 48)
        name_text = Text()
        name_text.append(name, style="bold")
        if product.get("is_ad"):
            name_text.append(" [AD]", style="bold red")
        url = product.get("url", "")
        if url:
            short_url = _truncate(url.replace("https://", "").replace("www.", ""), 55)
            name_text.append(f"\n{short_url}", style="dim cyan link " + url)

        # Price with color coding.
        price_text = _make_price_text(product, cheapest)

        # Source.
        source_text = _make_source_text(product)

        # Brand.
        brand = product.get("brand", "N/A")

        # Status.
        if "in_stock" in product:
            status = Text("✅" if product["in_stock"] else "❌")
        elif product.get("rating"):
            status = Text(f"⭐ {product['rating']:.1f}")
        else:
            status = Text("—", style="dim")

        table.add_row(
            str(idx), name_text, price_text, source_text, brand, status
        )

    console.print(table)

    # ---- Sizes column (show separately if any products have sizes) ----
    products_with_sizes = [p for p in products if p.get("sizes")]
    if products_with_sizes:
        console.print()
        sizes_table = Table(
            title="📏 Available Sizes",
            title_style="bold",
            border_style="bright_black",
            expand=True,
        )
        sizes_table.add_column("Product", min_width=30)
        sizes_table.add_column("Sizes", min_width=40)
        for p in products_with_sizes:
            sizes = p["sizes"]
            if isinstance(sizes, list):
                sizes = ", ".join(sizes)
            sizes_table.add_row(
                _truncate(p["name"], 40),
                sizes,
            )
        console.print(sizes_table)

    # ---- Price summary panel ----
    if len(prices) >= 2:
        avg_price = sum(prices) // len(prices)
        max_price = max(prices)

        # Find best deal (product with biggest discount).
        sale_products = [
            p for p in products
            if p.get("is_on_sale") and p.get("original_price", 0) > 0
        ]
        best_deal = None
        if sale_products:
            best_deal = max(
                sale_products,
                key=lambda p: (p["original_price"] - p["price"]) / p["original_price"]
            )

        # Build summary text.
        summary = Text()
        summary.append("📉 Cheapest    ", style="dim")
        summary.append(f"{_format_price(cheapest)}", style="bold green")
        cheapest_product = next(p for p in products if p["price"] == cheapest)
        summary.append(
            f"  ({cheapest_product.get('_source') or cheapest_product.get('store', '')})\n",
            style="dim",
        )
        summary.append("📈 Most Expensive  ", style="dim")
        summary.append(f"{_format_price(max_price)}\n", style="bold red")
        summary.append("📊 Average     ", style="dim")
        summary.append(f"{_format_price(avg_price)}\n", style="bold")

        if best_deal:
            discount = round(
                (1 - best_deal["price"] / best_deal["original_price"]) * 100
            )
            summary.append("🏷️ Best Deal   ", style="dim")
            summary.append(
                f"{best_deal['name'][:40]} — {_format_price(best_deal['price'])} ",
                style="bold yellow",
            )
            summary.append(f"(-{discount}%)", style="bold red")

        on_sale = len(sale_products)
        if on_sale:
            summary.append(f"\n🔥 On Sale     ", style="dim")
            summary.append(f"{on_sale} of {len(products)} products", style="bold")

        console.print()
        console.print(
            Panel(
                summary,
                title="[bold]💰 Price Comparison Summary[/]",
                border_style="green",
                padding=(1, 2),
            )
        )

    console.print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Create and return the argument parser."""
    sources = list_sources()

    parser = argparse.ArgumentParser(
        prog="shupping-helper",
        description=textwrap.dedent("""\
            Smart Price Comparison Tool
            Scrape product data from multiple sources and display structured results.
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "keyword",
        type=str,
        help='Product search keyword, e.g. "adidas samba"',
    )
    parser.add_argument(
        "--source", "-s",
        type=str,
        choices=sources + ["all"],
        default="odd",
        help='Data source to scrape (default: odd). Use "all" for combined search.',
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


def _search_all(keyword: str, max_pages: int) -> list[dict]:
    """Search all registered sources **in parallel** and return combined results.

    Uses ``ThreadPoolExecutor`` so every source scrapes concurrently.
    Timing info is printed per-source and overall.
    """
    import time as _time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    all_products: list[dict] = []
    scrapers = list_scrapers()

    console.print(
        f"\n  [dim]⚡ Searching [bold]{len(scrapers)}[/bold] sources in parallel …[/]"
    )
    overall_start = _time.perf_counter()

    def _run_scraper(slug: str, scraper_cls: type) -> tuple[str, str, list[dict], float]:
        """Run a single scraper and return (slug, name, products, elapsed)."""
        inst = scraper_cls()
        t0 = _time.perf_counter()
        try:
            products = inst.search(keyword, max_pages=max_pages)
            for p in products:
                p["_source"] = inst.NAME
            elapsed = _time.perf_counter() - t0
            return slug, inst.NAME, products, elapsed
        except Exception as exc:
            elapsed = _time.perf_counter() - t0
            logging.warning("%s failed: %s", inst.NAME, exc)
            return slug, inst.NAME, [], elapsed

    # Launch all scrapers concurrently.
    with ThreadPoolExecutor(max_workers=len(scrapers)) as pool:
        futures = {
            pool.submit(_run_scraper, slug, cls): slug
            for slug, cls in scrapers.items()
        }

        for future in as_completed(futures):
            slug, name, products, elapsed = future.result()
            if products:
                all_products.extend(products)
                console.print(
                    f"  [dim]━━━[/] [bold]{name}[/] → "
                    f"[green]{len(products)} product(s)[/] "
                    f"[dim]({elapsed:.1f}s)[/]"
                )
            else:
                console.print(
                    f"  [dim]━━━[/] [bold]{name}[/] → "
                    f"[yellow]0 products[/] [dim]({elapsed:.1f}s)[/]"
                )

    overall = _time.perf_counter() - overall_start
    console.print(
        f"  [dim]⚡ Done in [bold]{overall:.1f}s[/bold] "
        f"(scraped {len(scrapers)} sources in parallel)[/]"
    )

    # Sort by price (cheapest first), zero-price items last.
    all_products.sort(key=lambda p: p["price"] if p["price"] > 0 else float("inf"))

    return all_products


def main(argv: list[str] | None = None) -> int:
    """Entry point for the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # Configure logging.
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    keyword: str = args.keyword.strip()
    if not keyword:
        parser.error("Please provide a non-empty search keyword.")

    source: str = args.source

    # ---- Scrape ----
    try:
        if source == "all":
            products = _search_all(keyword, max_pages=args.pages)
            source_label = "All Sources"
        else:
            scraper_instance = get_scraper(source)
            console.print(
                f"\n  [dim]━━━ Searching[/] [bold]{scraper_instance.NAME}[/] [dim]…[/]"
            )
            products = scraper_instance.search(keyword, max_pages=args.pages)
            source_label = scraper_instance.NAME
    except KeyboardInterrupt:
        console.print("\n  [yellow]⏹ Interrupted by user.[/]")
        return 130
    except KeyError as exc:
        console.print(f"  [red]Error: {exc}[/]")
        return 1
    except Exception as exc:
        logging.error("Fatal error during scraping: %s", exc)
        return 1

    # ---- Display ----
    print_results(keyword, products, source_label=source_label)

    # ---- Optional export ----
    if args.export:
        try:
            if source == "all":
                exporter = get_scraper(list_sources()[0])
            else:
                exporter = get_scraper(source)
            out = exporter.export_to_csv(products, args.export)
            console.print(f"  [green]📁 Results exported to:[/] [bold]{out}[/]\n")
        except Exception as exc:
            logging.error("Failed to export CSV: %s", exc)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
