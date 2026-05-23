THEME_KEYWORDS = {
    "AI基建": ["ai", "cloud", "data center", "gpu", "server", "compute"],
    "光通訊": ["optical", "photonics", "laser", "fiber", "transceiver"],
    "HBM / 記憶體": ["memory", "dram", "storage", "flash", "ssd"],
    "電力 / 核電": ["power", "grid", "nuclear", "utility", "electrical"],
    "國防 / 無人機": ["defense", "drone", "military", "aerospace", "radar", "autonomous"],
    "機器人 / 自動化": ["robot", "automation", "humanoid", "industrial"],
    "資安": ["cyber", "security", "firewall", "endpoint"],
    "太空 / 衛星": ["space", "satellite", "orbital", "rocket"],
    "AI生技 / 醫療科技": ["biotech", "genomics", "drug", "medical", "healthcare"],
}

def detect_themes(text):
    text = text.lower()
    themes = []

    for theme, keywords in THEME_KEYWORDS.items():
        if any(k in text for k in keywords):
            themes.append(theme)

    return themes if themes else ["一般市場股"]

def theme_score(themes):
    weight = {
        "AI基建": 12,
        "光通訊": 12,
        "HBM / 記憶體": 12,
        "電力 / 核電": 11,
        "國防 / 無人機": 10,
        "機器人 / 自動化": 10,
        "資安": 9,
        "太空 / 衛星": 8,
        "AI生技 / 醫療科技": 8,
    }

    return min(sum(weight.get(t, 0) for t in themes), 18)