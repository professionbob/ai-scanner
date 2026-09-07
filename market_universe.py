"""Build free, best-effort US and Taiwan common-stock universes."""

import csv
import io
import re

import requests


NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
TWSE_LISTED_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_LISTED_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"

US_PRIORITY = [
    "ONDS", "AAOI", "AXTI", "DELL", "NBIS", "NVDA", "AMD", "AVGO", "MU", "TSM"
]
TW_PRIORITY = ["2330.TW", "3711.TW", "2356.TW"]

_NON_COMMON_NAME = re.compile(
    r"\b(?:ETF|ETN|FUND|TRUST|WARRANTS?|RIGHTS?|UNITS?|PREFERRED|PREFERENCE|"
    r"DEPOSITARY SHARES?|BENEFICIAL INTEREST|BONDS?|NOTES?)\b",
    re.IGNORECASE,
)
_US_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]*(?:[-.][A-Z])?$")


def dedupe(symbols):
    """Normalize symbols and retain their first occurrence."""
    result = []
    seen = set()
    for raw in symbols:
        symbol = str(raw or "").strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            result.append(symbol)
    return result


def _parse_pipe_table(text):
    lines = [line for line in text.splitlines() if line and not line.startswith("File Creation Time")]
    return list(csv.DictReader(io.StringIO("\n".join(lines)), delimiter="|"))


def _valid_us_row(row, symbol_key, allowed_exchanges=None):
    symbol = str(row.get(symbol_key, "")).strip().upper()
    name = str(row.get("Security Name", "")).strip()
    if allowed_exchanges and row.get("Exchange") not in allowed_exchanges:
        return None
    if row.get("ETF") != "N" or row.get("Test Issue") != "N":
        return None
    if row.get("Financial Status", "N") not in ("", "N"):
        return None
    if not _US_SYMBOL.fullmatch(symbol) or _NON_COMMON_NAME.search(name):
        return None
    # Yahoo Finance represents class separators with a dash.
    return symbol.replace(".", "-")


def parse_us_listings(nasdaq_text, other_text):
    """Parse Nasdaq Trader directories, retaining Nasdaq/NYSE/NYSE American common stock."""
    symbols = []
    for row in _parse_pipe_table(nasdaq_text):
        symbol = _valid_us_row(row, "Symbol")
        if symbol:
            symbols.append(symbol)
    for row in _parse_pipe_table(other_text):
        symbol = _valid_us_row(row, "ACT Symbol", {"N", "A"})
        if symbol:
            symbols.append(symbol)
    return dedupe(symbols)


def parse_tw_listings(rows, suffix):
    """Parse TWSE/MOPS company records into Yahoo Finance symbols."""
    symbols = []
    for row in rows:
        raw = str(row.get("公司代號", row.get("SecuritiesCompanyCode", ""))).strip()
        # Four numeric digits identify regular Taiwan company shares and exclude ETFs/warrants.
        if re.fullmatch(r"[1-9]\d{3}", raw):
            symbols.append(f"{raw}{suffix}")
    return dedupe(symbols)


def _get(session, url):
    response = session.get(url, timeout=20, headers={"User-Agent": "ai-scanner/2"})
    response.raise_for_status()
    return response


def get_us_market(fallback, session=requests):
    """Download the US universe, falling back atomically if either directory fails."""
    try:
        symbols = parse_us_listings(
            _get(session, NASDAQ_LISTED_URL).text,
            _get(session, OTHER_LISTED_URL).text,
        )
        if not symbols:
            raise ValueError("empty US listing directory")
        return dedupe(US_PRIORITY + symbols), False
    except (requests.RequestException, ValueError, KeyError, csv.Error) as error:
        print(f"美股名單來源失敗，使用既有股票池：{type(error).__name__}")
        return dedupe(US_PRIORITY + fallback), True


def get_tw_market(fallback, session=requests):
    """Download listed and OTC company universes, or use the complete old pool."""
    try:
        twse = _get(session, TWSE_LISTED_URL).json()
        tpex = _get(session, TPEX_LISTED_URL).json()
        symbols = parse_tw_listings(twse, ".TW") + parse_tw_listings(tpex, ".TWO")
        if not symbols:
            raise ValueError("empty Taiwan listing directory")
        return dedupe(TW_PRIORITY + symbols), False
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        print(f"台股名單來源失敗，使用既有股票池：{type(error).__name__}")
        return dedupe(TW_PRIORITY + fallback), True


def make_batch(universe, cursor, size, priority, dynamic_priority=None):
    """Select a circular market slice plus per-run priority symbols without duplicates."""
    universe = dedupe(universe)
    if not universe or size <= 0:
        return dedupe(priority + (dynamic_priority or [])), []
    cursor = max(0, int(cursor)) % len(universe)
    count = min(size, len(universe))
    indices = [(cursor + offset) % len(universe) for offset in range(count)]
    market_slice = [universe[index] for index in indices]
    # Priority symbols never affect the market slice or its cursor.
    batch = dedupe(priority + (dynamic_priority or []) + market_slice)
    return batch, market_slice


def advance_cursor(universe, cursor, market_slice, completed):
    """Advance past only the contiguous market-slice symbols actually completed."""
    universe = dedupe(universe)
    if not universe:
        return 0
    completed = set(completed)
    completed_count = 0
    for symbol in market_slice:
        if symbol not in completed:
            break
        completed_count += 1
    return (max(0, int(cursor)) % len(universe) + completed_count) % len(universe)
