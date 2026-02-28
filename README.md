# 🛒 Shupping Helper – Smart Price Comparison Tool

Multi-source product scraper supporting **Tokopedia** and **Seek Indonesia** (Shopify).

---

## Features

- 🔍 Search products on **Tokopedia** and **Seek Indonesia** by keyword
- 💰 Prices converted to clean numeric integers (IDR)
- ⭐ Ratings, store names, and direct product URLs
- 🏷️ Sale price detection with original price comparison (Seek Indonesia)
- 📦 Sizes, colours, stock status for Seek Indonesia products
- 🛡️ Anti-bot handling: rotating User-Agent, random delays, retries
- 📦 Multiple scraping strategies with automatic fallback per source
- 📁 Optional CSV export

## Requirements

- Python 3.10+
- Dependencies listed in `requirements.txt`

## Installation

```bash
# Clone the repository
git clone https://github.com/fachrulrzy/shupping-helper.git
cd shupping-helper

# Create a virtual environment (recommended)
python -m venv .venv

# Activate the virtual environment
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux / macOS:
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# (Optional) Install Playwright browsers for headless fallback
python -m playwright install chromium
```

## Usage

### Basic search (Tokopedia, default)

```bash
python main.py "adidas samba"
```

### Search Seek Indonesia

```bash
python main.py "adidas samba" --source seek
```

### Multi-page search

```bash
python main.py "adidas samba" --pages 3
python main.py "adidas samba" --source seek --pages 2
```

### Export results to CSV

```bash
python main.py "adidas samba" --export results.csv
python main.py "adidas samba" --source seek --export seek_results.csv
```

### Verbose logging

```bash
python main.py "adidas samba" --verbose
```

## Example Output

```
══════════════════════════════════════════════════════════════
  🔍  Searching: adidas samba
══════════════════════════════════════════════════════════════

  Tokopedia Results (20 products):

  1. Adidas Samba OG White Black
     Price  : Rp 1.450.000
     Store  : Adidas Official Store
     Rating : ⭐ 4.9
     Link   : https://www.tokopedia.com/...
     ────────────────────────────────────────────────────────────

  2. Adidas Samba Classic White
     Price  : Rp 1.390.000
     Store  : XYZ Store
     Rating : ⭐ 4.8
     Link   : https://www.tokopedia.com/...
     ────────────────────────────────────────────────────────────
```

## Project Structure

```
shupping-helper/
├── scraper/
│   ├── __init__.py
│   ├── tokopedia.py      # Tokopedia scraper (GQL, HTML, Playwright)
│   └── seek.py           # Seek Indonesia scraper (Shopify JSON API, Playwright)
├── main.py                # CLI entry point (multi-source)
├── requirements.txt       # Python dependencies
├── README.md
└── LICENSE
```

## Architecture

| Layer | File | Responsibility |
|-------|------|----------------|
| CLI | `main.py` | Argument parsing, source routing, formatted output, CSV export |
| Scraper | `scraper/tokopedia.py` | Tokopedia: GQL API, HTML scraping, Playwright fallback |
| Scraper | `scraper/seek.py` | Seek Indonesia: Shopify Search API, Products JSON, Playwright fallback |

## Edge Cases Handled

- Missing ratings → defaults to `0.0`
- Sponsored / TopAds products → flagged with `[AD]` tag
- Price format inconsistencies (`Rp 1.450.000`, `Rp1,390,000`, plain int) → all normalised to `int`
- Lazy-loaded elements → handled by Playwright fallback with progressive scrolling
- Network failures → exponential backoff retries (up to 3 attempts)

## License

See [LICENSE](LICENSE) for details.
