"""Time-bounded discovery of liquid stocks mentioned in current market news."""

import re
import time
from urllib.parse import quote_plus
from xml.etree import ElementTree

import pandas as pd
import requests
import yfinance as yf


NEWS_QUERIES = (
    "US stock market movers", "NASDAQ stocks AI", "semiconductor stocks",
    "data center stocks", "defense space stocks", "energy stocks",
    "台股 AI 股票", "台股 半導體", "台股 盤中 焦點",
)
NEWS_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
SYMBOL = re.compile(r"(?:\$|NASDAQ:\s*|NYSE:\s*)([A-Z][A-Z0-9.-]{0,9})\b")
TW_SYMBOL = re.compile(r"\b([1-9]\d{3})(?:\.TW|\.TWO)?\b")


def _remaining(deadline, clock, maximum):
    remaining = deadline - clock()
    if remaining <= 0:
        raise TimeoutError("dynamic-priority deadline expired")
    return max(0.1, min(maximum, remaining))


def fetch_news_candidates(deadline, session=requests, clock=time.monotonic):
    """Fetch nine RSS searches, checking the shared deadline around every call."""
    candidates = []
    for query in NEWS_QUERIES:
        timeout = _remaining(deadline, clock, 10)
        response = session.get(
            NEWS_URL.format(query=quote_plus(query)),
            timeout=timeout,
            headers={"User-Agent": "ai-scanner/2"},
        )
        response.raise_for_status()
        _remaining(deadline, clock, 10)
        text = " ".join(node.text or "" for node in ElementTree.fromstring(response.content).iter("title"))
        candidates.extend(SYMBOL.findall(text.upper()))
        if "台股" in query:
            candidates.extend(f"{code}.TW" for code in TW_SYMBOL.findall(text.upper()))
    return list(dict.fromkeys(candidates))


def _qualified_from_download(frame, symbols):
    selected = []
    for symbol in symbols:
        try:
            data = frame[symbol] if isinstance(frame.columns, pd.MultiIndex) else frame
            close = data["Close"].dropna()
            volume = data["Volume"].dropna()
            minimum_price = 10 if symbol.endswith((".TW", ".TWO")) else 5
            minimum_volume = 100000 if symbol.endswith((".TW", ".TWO")) else 500000
            if len(close) >= 20 and len(volume) >= 20:
                if float(close.iloc[-1]) >= minimum_price and float(volume.tail(20).mean()) >= minimum_volume:
                    selected.append(symbol)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    return selected


def update_dynamic_priority(
    overall_deadline,
    *,
    budget_seconds=180,
    max_quote_candidates=12,
    clock=time.monotonic,
    news_fetcher=fetch_news_candidates,
    downloader=yf.download,
):
    """Return (US, TW, success); any timeout/error atomically yields fixed-only lists."""
    deadline = min(overall_deadline, clock() + budget_seconds)
    try:
        _remaining(deadline, clock, 10)
        candidates = list(dict.fromkeys(news_fetcher(deadline)))[:max_quote_candidates]
        _remaining(deadline, clock, 30)
        if not candidates:
            return [], [], True
        frame = downloader(
            candidates,
            period="1mo",
            interval="1d",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
            timeout=_remaining(deadline, clock, 30),
        )
        _remaining(deadline, clock, 30)
        qualified = _qualified_from_download(frame, candidates)
        return (
            [symbol for symbol in qualified if not symbol.endswith((".TW", ".TWO"))],
            [symbol for symbol in qualified if symbol.endswith((".TW", ".TWO"))],
            True,
        )
    except Exception as error:
        print(f"浮動優先名單更新失敗，僅使用固定優先名單：{type(error).__name__}")
        return [], [], False
