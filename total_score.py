def calculate_total_score(

    technical_score,
    theme_score,
    rs_score,
    narrative_score,
    earnings_score
):

    total = (

        technical_score * 0.4
        + theme_score * 0.25
        + rs_score * 0.15
        + narrative_score * 0.1
        + earnings_score * 0.1
    )

    return round(total, 2)