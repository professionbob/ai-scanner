"""Best-effort dynamic scan priorities built from free news and daily prices.

The module is deliberately dependency-injected: network adapters are thin, while
parsing, scoring, caching, and ordering can be tested without internet access.
"""

from datetime import datetime, timezone
import math
import re

import pandas as pd
import requests
import yfinance as yf


YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
NEWS_QUERIES = (
    "AI semiconductor", "optical networking", "memory chips", "nuclear power grid",
    "defense drone", "robotics automation", "cybersecurity", "space satellite",
    "AI biotech",
)
THEME_KEYWORDS = {
    "AI半導體": ("ai", "semiconductor", "gpu", "data center"),
    "光通訊": ("optical", "photonics", "transceiver", "fiber"),
    "記憶體": ("memory", "dram", "nand", "hbm"),
    "電力/核能": ("power", "grid", "nuclear", "utility"),
    "國防/無人機": ("defense", "military", "drone"),
    "機器人": ("robot", "automation", "humanoid"),
    "資安": ("cybersecurity", "cyber security", "ransomware"),
    "太空/衛星": ("space", "satellite", "orbital", "rocket"),
    "AI生技": ("biotech", "genomics", "drug discovery", "clinical"),
}
CATALYST_KEYWORDS = {
    "財報": ("earnings", "revenue", "profit", "guidance", "財報", "營收"),
    "訂單": ("order", "contract", "deal", "訂單", "合約"),
    "併購": ("acquire", "acquisition", "merger", "takeover", "併購", "收購"),
    "政策": ("policy", "government", "tariff", "subsidy", "regulation", "政策"),
    "分析師調整": ("upgrade", "downgrade", "price target", "initiates", "目標價"),
}
US_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z])?$")
TW_SYMBOL = re.compile(r"^[1-9]\d{3}\.TW(?:O)?$")


def _utc(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(float(value), timezone.utc)


def fetch_news(session=requests):
    """Fetch bounded Yahoo Finance search results whose relatedTickers are explicit."""
    articles = []
    for query in NEWS_QUERIES:
        response = session.get(
            YAHOO_SEARCH_URL,
            params={"q": query, "quotesCount": 0, "newsCount": 20},
            headers={"User-Agent": "ai-scanner/3"}, timeout=15,
        )
        response.raise_for_status()
        articles.extend(response.json().get("news", []))
    return articles


def parse_news_items(items, valid_symbols, now=None, max_age_hours=72):
    """Attach articles only via provider-supplied relatedTickers, never name guessing."""
    now = _utc(now or datetime.now(timezone.utc))
    valid = {str(s).upper() for s in valid_symbols}
    parsed = []
    seen = set()
    for item in items:
        try:
            published = _utc(item["providerPublishTime"])
            age = (now - published).total_seconds() / 3600
        except (KeyError, TypeError, ValueError, OSError, OverflowError):
            continue
        if age < 0 or age > max_age_hours:
            continue
        title = str(item.get("title", "")).strip()
        link = str(item.get("link", "")).strip()
        text = title.lower()
        catalysts = [name for name, words in CATALYST_KEYWORDS.items() if any(w in text for w in words)]
        themes = [name for name, words in THEME_KEYWORDS.items() if any(w in text for w in words)]
        for raw in item.get("relatedTickers") or []:
            symbol = str(raw).upper()
            if symbol not in valid or not (US_SYMBOL.fullmatch(symbol) or TW_SYMBOL.fullmatch(symbol)):
                continue
            key = (symbol, link or title)
            if key in seen:
                continue
            seen.add(key)
            parsed.append({"symbol": symbol, "title": title, "link": link,
                           "published_at": published.isoformat(), "age_hours": age,
                           "catalysts": catalysts, "themes": themes})
    return parsed


def default_price_loader(symbol):
    return yf.download(symbol, period="3mo", interval="1d", auto_adjust=True,
                       progress=False, threads=False)


def _column(frame, name):
    value = frame[name]
    if isinstance(value, pd.DataFrame):
        if value.shape[1] != 1:
            raise ValueError(f"ambiguous {name} price columns")
        value = value.iloc[:, 0]
    return pd.to_numeric(value, errors="coerce").dropna()


def momentum_score(frame, benchmark):
    """Score 5/20-day relative strength, volume expansion and benchmark trend."""
    if frame is None or benchmark is None or len(frame) < 21 or len(benchmark) < 21:
        raise ValueError("insufficient price history")
    close = _column(frame, "Close")
    volume = _column(frame, "Volume")
    bench = _column(benchmark, "Close")
    if len(close) < 21 or len(volume) < 20 or len(bench) < 21:
        raise ValueError("insufficient valid price history")
    r5 = close.iloc[-1] / close.iloc[-6] - 1
    r20 = close.iloc[-1] / close.iloc[-21] - 1
    b5 = bench.iloc[-1] / bench.iloc[-6] - 1
    b20 = bench.iloc[-1] / bench.iloc[-21] - 1
    vol_ratio = volume.iloc[-1] / max(volume.iloc[-20:].mean(), 1)
    trend = close.iloc[-1] / close.iloc[-20:].mean() - 1
    score = (r5 - b5) * 180 + (r20 - b20) * 100 + min(max(vol_ratio - 1, -0.5), 2) * 8 + trend * 80
    return round(max(0, min(60, 25 + score)), 2), {
        "relative_strength_5d": round((r5 - b5) * 100, 2),
        "relative_strength_20d": round((r20 - b20) * 100, 2),
        "volume_ratio": round(float(vol_ratio), 2), "trend_vs_ma20": round(trend * 100, 2),
    }


def build_dynamic_priorities(us_universe, tw_universe, news_items, price_loader=default_price_loader, now=None):
    """Build both lists atomically; callers fall back if any source/score operation fails."""
    now = _utc(now or datetime.now(timezone.utc))
    valid = set(us_universe) | set(tw_universe)
    parsed = parse_news_items(news_items, valid, now)
    by_symbol = {}
    for article in parsed:
        if article["catalysts"]:
            by_symbol.setdefault(article["symbol"], []).append(article)
    # Bounded quote work: newest and strongest catalyst coverage first.
    candidates = sorted(by_symbol, key=lambda s: (-sum(bool(a["catalysts"]) for a in by_symbol[s]),
                                                   min(a["age_hours"] for a in by_symbol[s]), s))[:50]
    benchmarks = {"US": price_loader("SPY"), "TW": price_loader("^TWII")}
    rows = {"US": [], "TW": []}
    for symbol in candidates:
        market = "TW" if symbol.endswith((".TW", ".TWO")) else "US"
        frame = price_loader(symbol)
        avg_volume = float(_column(frame, "Volume").tail(20).mean())
        min_volume = 100_000 if market == "TW" else 500_000
        if not math.isfinite(avg_volume) or avg_volume < min_volume:
            continue
        momentum, metrics = momentum_score(frame, benchmarks[market])
        articles = by_symbol[symbol]
        catalyst_count = sum(bool(a["catalysts"]) for a in articles)
        freshness = max(0, 1 - min(a["age_hours"] for a in articles) / 72)
        news_score = min(40, catalyst_count * 12 + len(articles) * 3 + freshness * 10)
        themes = sorted({t for a in articles for t in a["themes"]})
        catalysts = sorted({c for a in articles for c in a["catalysts"]})
        total = round(news_score + momentum, 2)
        latest = max(articles, key=lambda a: a["published_at"])
        reasons = catalysts + themes + [f"5日相對強度 {metrics['relative_strength_5d']:+.1f}%",
                                        f"量比 {metrics['volume_ratio']:.1f}x"]
        rows[market].append({"symbol": symbol, "score": total, "reasons": reasons,
                             "news_time": latest["published_at"], "catalyst": latest["title"],
                             "metrics": metrics, "themes": themes, "momentum_score": momentum})
    for market, maximum in (("US", 15), ("TW", 10)):
        theme_scores = {}
        for row in rows[market]:
            for theme in row["themes"]:
                theme_scores.setdefault(theme, []).append(row["momentum_score"])
        theme_scores = {theme: sum(values) / len(values) for theme, values in theme_scores.items()}
        for row in rows[market]:
            strongest = max(row["themes"], key=lambda t: theme_scores[t], default=None)
            if strongest:
                rotation_bonus = max(0, min(10, (theme_scores[strongest] - 25) * 0.3))
                row["score"] = round(row["score"] + rotation_bonus, 2)
                if rotation_bonus:
                    row["reasons"].insert(0, f"{strongest}板塊強勢")
            row.pop("themes", None)
            row.pop("momentum_score", None)
        rows[market] = sorted(rows[market], key=lambda row: (-row["score"], row["symbol"]))[:maximum]
    return rows["US"], rows["TW"]


def refresh_dynamic_state(state, us_universe, tw_universe, now=None,
                          news_loader=fetch_news, price_loader=default_price_loader, ttl_minutes=60):
    """Use a valid 60-minute cache, otherwise rebuild; failures return fixed-only lists."""
    now = _utc(now or datetime.now(timezone.utc))
    try:
        updated = _utc(datetime.fromisoformat(state.get("last_dynamic_update", "")))
        us = state["dynamic_us_priority"]
        tw = state["dynamic_tw_priority"]
        if (now - updated).total_seconds() < ttl_minutes * 60 and isinstance(us, list) and isinstance(tw, list):
            if all(isinstance(x, dict) and x.get("symbol") for x in us + tw):
                return us, tw, False, False
    except (KeyError, TypeError, ValueError):
        pass
    old_us = state.get("dynamic_us_priority")
    old_tw = state.get("dynamic_tw_priority")
    old_us = old_us if isinstance(old_us, list) else []
    old_tw = old_tw if isinstance(old_tw, list) else []
    old_signature = ([x.get("symbol") for x in old_us if isinstance(x, dict)],
                     [x.get("symbol") for x in old_tw if isinstance(x, dict)])
    try:
        us, tw = build_dynamic_priorities(us_universe, tw_universe, news_loader(), price_loader, now)
    except Exception as error:
        print(f"浮動優先資料更新失敗，僅使用固定名單：{type(error).__name__}")
        us, tw = [], []
    state["dynamic_us_priority"], state["dynamic_tw_priority"] = us, tw
    state["last_dynamic_update"] = now.isoformat()
    signature = ([x["symbol"] for x in us], [x["symbol"] for x in tw])
    return us, tw, True, signature != old_signature


def format_change_message(us, tw):
    lines = ["🔄 浮動優先名單更新"]
    for label, rows in (("美股", us), ("台股", tw)):
        if rows:
            lines.append(label + "：")
            for row in rows:
                reason = "、".join(row.get("reasons", [])[:2]) or "新聞與動能"
                lines.append(f"• {row['symbol']}｜{reason}｜{row.get('catalyst', '')[:70]}")
    return "\n".join(lines)
