THEME_KEYWORDS = {
    "AI基建": ["ai", "cloud", "data center", "gpu", "server", "compute"],
    "光通訊": ["optical", "photonics", "laser", "fiber", "transceiver"],
    "HBM / 記憶體": ["memory", "dram", "storage", "flash", "ssd"],

    "玻璃基板 / TGV": [
        "glass substrate",
        "glass core",
        "tgv",
        "through glass via",
        "lide",
        "laser induced deep etching",
        "panel level packaging",
        "advanced packaging",
        "glass interposer",
        "glass package"
    ],

    "電力 / 核電": ["power", "grid", "nuclear", "utility", "electrical"],
    "國防 / 無人機": ["defense", "drone", "military", "aerospace", "radar", "autonomous"],
    "機器人 / 自動化": ["robot", "automation", "humanoid", "industrial"],
    "資安": ["cyber", "security", "firewall", "endpoint"],
    "太空 / 衛星": ["space", "satellite", "orbital", "rocket"],
    "AI生技 / 醫療科技": ["biotech", "genomics", "drug", "medical", "healthcare"],
}


LEADING_THEMES = [
    "AI基建",
    "光通訊",
    "HBM / 記憶體",
    "玻璃基板 / TGV",
]


def detect_themes(text):
    text = str(text).lower()
    themes = []

    for theme, keywords in THEME_KEYWORDS.items():
        if any(k.lower() in text for k in keywords):
            themes.append(theme)

    return themes if themes else ["一般市場股"]


def theme_score(themes):
    weight = {
        "AI基建": 12,
        "光通訊": 12,
        "HBM / 記憶體": 12,
        "玻璃基板 / TGV": 12,
        "電力 / 核電": 11,
        "國防 / 無人機": 10,
        "機器人 / 自動化": 10,
        "資安": 9,
        "太空 / 衛星": 8,
        "AI生技 / 醫療科技": 8,
        "一般市場股": 0,
    }

    return min(sum(weight.get(t, 0) for t in themes), 18)


def theme_rotation_bonus(themes):
    bonus = 0

    for theme in themes:
        if theme in LEADING_THEMES:
            bonus += 3

    return min(bonus, 6)


def total_theme_score(text):
    themes = detect_themes(text)

    score = (
        theme_score(themes)
        + theme_rotation_bonus(themes)
    )
from themes import THEMES
from supply_chain_weight import SUPPLY_CHAIN_WEIGHT


def calculate_theme_strength(
    stock_data,
    theme_name
):

    theme = THEMES[theme_name]

    total_score = 0

    for category, tickers in theme.items():

        weight = SUPPLY_CHAIN_WEIGHT.get(category, 5)

        for ticker in tickers:

            if ticker not in stock_data:
                continue

            data = stock_data[ticker]

            technical_score = data["technical_score"]

            rs_score = data["rs_score"]

            breakout = data["breakout"]

            stock_score = (
                technical_score
                + rs_score
            )

            if breakout:
                stock_score += 5

            total_score += stock_score * weight

    return total_score
    return {
        "themes": themes,
        "theme_score": score
    }