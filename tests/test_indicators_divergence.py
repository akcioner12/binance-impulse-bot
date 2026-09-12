import indicators


def test_find_local_peaks_detects_single_peak():
    values = [1, 2, 3, 4, 5, 4, 3, 2, 1]
    peaks = indicators.find_local_peaks(values, window=2)
    assert 4 in peaks  # индекс значения 5


def test_find_local_troughs_detects_single_trough():
    values = [5, 4, 3, 2, 1, 2, 3, 4, 5]
    troughs = indicators.find_local_troughs(values, window=2)
    assert 4 in troughs  # индекс значения 1


def test_detect_bearish_divergence_true_when_price_higher_high_rsi_lower_high():
    # Два пика цены: первый ниже (индекс 4, значение 10), второй выше (индекс 12, значение 12)
    closes = [1, 2, 3, 5, 10, 5, 3, 2, 3, 5, 8, 11, 12, 11, 8, 5, 3, 2, 1]
    rsi_values = [None, None, None, None, 80.0, None, None, None, None, None, None, None, 60.0, None, None, None, None, None, None]
    # Заполним остальные индексы числами, чтобы find_local_peaks не спотыкался о None вне пиков
    rsi_values = [50.0 if v is None else v for v in rsi_values]
    rsi_values[4] = 80.0
    rsi_values[12] = 60.0

    assert indicators.detect_bearish_divergence(closes, rsi_values, window=2) is True


def test_detect_bearish_divergence_false_when_no_new_price_high():
    closes = [1, 2, 3, 5, 10, 5, 3, 2, 3, 5, 8, 9, 9.5, 9, 8, 5, 3, 2, 1]
    rsi_values = [50.0] * len(closes)
    rsi_values[4] = 60.0
    rsi_values[12] = 80.0  # RSI выше, но цена НЕ сделала новый хай -> не дивергенция

    assert indicators.detect_bearish_divergence(closes, rsi_values, window=2) is False


def test_detect_bullish_divergence_true_when_price_lower_low_rsi_higher_low():
    # Два дна цены: первое выше (индекс 4, значение 1), второе ниже (индекс 12, значение -3)
    closes = [10, 8, 6, 3, 1, 3, 6, 8, 7, 4, 1, -1, -3, -1, 4, 8, 10, 11, 12]
    rsi_values = [50.0] * len(closes)
    rsi_values[4] = 20.0
    rsi_values[12] = 35.0
    assert indicators.detect_bullish_divergence(closes, rsi_values, window=2) is True


def test_detect_divergence_false_when_less_than_two_peaks():
    closes = [1, 2, 3, 4, 5, 4, 3, 2, 1]
    rsi_values = [50.0] * len(closes)
    assert indicators.detect_bearish_divergence(closes, rsi_values, window=2) is False


def test_detect_divergence_ignores_none_rsi_indices():
    # Пик цены на индексе, где RSI ещё None (недостаточно данных) — должен игнорироваться
    closes = [1, 2, 3, 5, 10, 5, 3, 2, 3, 5, 8, 11, 12, 11, 8, 5, 3, 2, 1]
    rsi_values = [None] * len(closes)
    rsi_values[12] = 60.0
    # Только один валидный пик (индекс 4 имеет RSI=None) -> недостаточно точек для сравнения
    assert indicators.detect_bearish_divergence(closes, rsi_values, window=2) is False
