"""Market quotes and history via yfinance, with explicit source timestamps."""

from datetime import datetime, timezone
import re

import pandas as pd


def fetch_latest_quote(symbol):
    """Return last available daily close; never substitute a synthetic price."""
    try:
        import yfinance as yf
        history = yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=False)
        if history.empty or "Close" not in history:
            return {"ok": False, "error": "No quote data was returned for this symbol."}
        valid = history.dropna(subset=["Close"])
        if valid.empty:
            return {"ok": False, "error": "The data source returned no valid closing price."}
        latest = valid.iloc[-1]
        market_time = valid.index[-1]
        return {
            "ok": True,
            "symbol": symbol,
            "price": float(latest["Close"]),
            "currency": "Source currency",
            "market_time": market_time.isoformat(),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "history": history.reset_index(),
        }
    except Exception as exc:
        if isinstance(exc, ImportError):
            return {"ok": False, "error": "Market data needs yfinance. Install project dependencies with: python -m pip install -r requirements.txt"}
        return {"ok": False, "error": f"Market data could not be fetched: {exc}"}


def fetch_india_bullion_rates():
    """Read the latest published Indian bullion benchmark from IBJA's public page.

    IBJA publishes gold per 10 g and silver per kg. Values exclude GST and
    jewellery making charges. If the page structure changes, fail closed.
    """
    try:
        import requests
        from bs4 import BeautifulSoup

        response = requests.get(
            "https://www.ibjarates.com/",
            headers={"User-Agent": "Ledger personal finance dashboard"},
            timeout=12,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        tables = soup.find_all("table")
        date_pattern = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
        table_candidates = []
        for table in tables:
            table_text = " ".join(table.stripped_strings).lower()
            if "silver" not in table_text or "999" not in table_text:
                continue
            candidates = []
            for row in table.find_all("tr"):
                cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                if len(cells) < 7 or not date_pattern.match(cells[0]):
                    continue
                numbers = []
                for cell in cells[1:]:
                    cleaned = re.sub(r"[^0-9.]", "", cell.replace(",", ""))
                    try:
                        numbers.append(float(cleaned))
                    except ValueError:
                        numbers.append(None)
                # IBJA table columns begin Gold 999 and end Silver 999.
                if len(numbers) >= 6 and numbers[0] and numbers[5]:
                    candidates.append((cells[0], numbers[0], numbers[5]))
            if candidates:
                table_candidates.append(candidates)
        if not table_candidates:
            return {"ok": False, "error": "IBJA did not publish a readable bullion rate."}

        # The public page lists the AM table followed by the PM table; use the
        # newest row from the last matching table (PM when available).
        latest_rows = table_candidates[-1]
        date_text, gold, silver = max(
            latest_rows,
            key=lambda row: datetime.strptime(row[0], "%d/%m/%Y"),
        )
        market_date = datetime.strptime(date_text, "%d/%m/%Y").date().isoformat()
        return {
            "ok": True,
            "source": "India Bullion and Jewellers Association (IBJA)",
            "market_date": market_date,
            "gold_999_per_10g": gold,
            "silver_999_per_kg": silver,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {"ok": False, "error": f"Indian bullion rates could not be fetched: {exc}"}


def fetch_history(symbol, period="1y"):
    try:
        import yfinance as yf
        history = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=False)
        if history.empty:
            return None, "No historical market data is available for this symbol."
        return history.reset_index(), None
    except Exception as exc:
        if isinstance(exc, ImportError):
            return None, "Market history needs yfinance. Install project dependencies with: python -m pip install -r requirements.txt"
        return None, f"Market history could not be fetched: {exc}"
