# 🛒 Shupping Helper – Smart Price Comparison Tool

**Phase 1** — Tokopedia product scraper with structured terminal output.

---

## Features

- 🔍 Search products on Tokopedia by keyword
- 💰 Prices converted to clean numeric integers (IDR)
- ⭐ Ratings, store names, and direct product URLs
- 🛡️ Anti-bot handling: rotating User-Agent, random delays, retries
- 📦 Three scraping strategies with automatic fallback:
  1. **GraphQL API** – fast & structured (primary)
  2. **Static HTML** – requests + BeautifulSoup (secondary)
  3. **Playwright** – headless Chromium browser (ultimate fallback)
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

### Basic search

```bash
python main.py "adidas samba"
```

### Multi-page search

```bash
python main.py "adidas samba" --pages 3
```

### Export results to CSV

```bash
python main.py "adidas samba" --export results.csv
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
│   └── tokopedia.py      # Tokopedia scraper (GQL, HTML, Playwright)
├── main.py                # CLI entry point
├── requirements.txt       # Python dependencies
├── README.md
└── LICENSE
```

## Architecture

| Layer | File | Responsibility |
|-------|------|----------------|
| CLI | `main.py` | Argument parsing, formatted output, CSV export trigger |
| Scraper | `scraper/tokopedia.py` | URL building, HTTP requests, HTML/GQL parsing, data normalisation |

## Edge Cases Handled

- Missing ratings → defaults to `0.0`
- Sponsored / TopAds products → flagged with `[AD]` tag
- Price format inconsistencies (`Rp 1.450.000`, `Rp1,390,000`, plain int) → all normalised to `int`
- Lazy-loaded elements → handled by Playwright fallback with progressive scrolling
- Network failures → exponential backoff retries (up to 3 attempts)

## License

See [LICENSE](LICENSE) for details.
