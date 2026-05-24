def calculate_rs(
    stock_return,
    benchmark_return
):

    rs = (
        stock_return
        - benchmark_return
    )

    return round(rs, 2)