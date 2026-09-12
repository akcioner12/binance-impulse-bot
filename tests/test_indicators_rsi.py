import indicators


def test_rsi_length_matches_input():
    values = [float(i) for i in range(30)]
    result = indicators.rsi(values, period=14)
    assert len(result) == len(values)


def test_rsi_first_period_values_are_none():
    values = [float(i) for i in range(30)]
    result = indicators.rsi(values, period=14)
    assert all(v is None for v in result[:14])
    assert result[14] is not None


def test_rsi_monotonic_increase_approaches_100():
    values = [float(i) for i in range(1, 31)]  # строго растущая цена
    result = indicators.rsi(values, period=14)
    assert result[-1] == 100.0


def test_rsi_monotonic_decrease_approaches_0():
    values = [float(30 - i) for i in range(30)]  # строго падающая цена
    result = indicators.rsi(values, period=14)
    assert result[-1] == 0.0


def test_rsi_flat_prices_gives_neutral_value():
    values = [10.0] * 30  # цена не меняется
    result = indicators.rsi(values, period=14)
    # avg_gain = avg_loss = 0 -> RSI = 100 по формуле (нет падений вообще)
    assert result[-1] == 100.0


def test_rsi_too_short_returns_all_none():
    values = [10.0, 11.0, 12.0]
    result = indicators.rsi(values, period=14)
    assert all(v is None for v in result)
