from collections import defaultdict


def build_leaderboard(results, top_n=10):
    if not results:
        return None

    sorted_results = sorted(
        results,
        key=lambda x: x.get("leader_score", x.get("score", 0)),
        reverse=True
    )

    msg = "🏆 Market Leaders Top 10\n\n"

    for i, r in enumerate(sorted_results[:top_n], start=1):
        ticker = r.get("ticker", "N/A")
        score = r.get("score", 0)
        leader_score = r.get("leader_score", 0)
        themes = ", ".join(r.get("themes", []))

        msg += (
            f"{i}. {ticker}\n"
            f"Score：{score}\n"
            f"Leader：{leader_score}/100\n"
            f"Theme：{themes}\n\n"
        )

    return msg.strip()


def build_sector_rotation(results):
    if not results:
        return None

    theme_data = defaultdict(lambda: {
        "count": 0,
        "total_score": 0,
        "total_leader_score": 0,
        "tickers": []
    })

    for r in results:
        themes = r.get("themes", ["一般"])
        score = r.get("score", 0)
        leader_score = r.get("leader_score", 0)
        ticker = r.get("ticker", "")

        for theme in themes:
            theme_data[theme]["count"] += 1
            theme_data[theme]["total_score"] += score
            theme_data[theme]["total_leader_score"] += leader_score
            theme_data[theme]["tickers"].append(ticker)

    ranking = []

    for theme, data in theme_data.items():
        avg_score = data["total_score"] / data["count"]
        avg_leader = data["total_leader_score"] / data["count"]

        rotation_score = (
            data["count"] * 10
            + avg_score
            + avg_leader * 0.5
        )

        ranking.append({
            "theme": theme,
            "count": data["count"],
            "avg_score": round(avg_score, 1),
            "avg_leader": round(avg_leader, 1),
            "rotation_score": round(rotation_score, 1),
            "tickers": data["tickers"][:5]
        })

    ranking = sorted(
        ranking,
        key=lambda x: x["rotation_score"],
        reverse=True
    )

    msg = "📊 Sector / Theme Rotation Ranking\n\n"

    for i, r in enumerate(ranking, start=1):
        msg += (
            f"{i}. {r['theme']}\n"
            f"Rotation Score：{r['rotation_score']}\n"
            f"訊號數：{r['count']}\n"
            f"平均分數：{r['avg_score']}\n"
            f"平均 Leader：{r['avg_leader']}/100\n"
            f"代表股票：{', '.join(r['tickers'])}\n\n"
        )

    return msg.strip()