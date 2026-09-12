"""
Технические индикаторы для детектора манипуляции.

Все функции — чистые вычисления над списком свечей/значений, без сетевых
вызовов. Свеча — dict формата market_data.py:
{"open_time": int, "open": float, "high": float, "low": float, "close": float, "volume": float}
"""


def ema(values: list[float], period: int) -> list[float]:
    """Экспоненциальная скользящая средняя. Длина результата равна длине входа."""
    if not values:
        return []
    k = 2 / (period + 1)
    result = [values[0]]
    for price in values[1:]:
        result.append(price * k + result[-1] * (1 - k))
    return result


def trend_direction(candles: list[dict], period: int = 20) -> str:
    """
    Направление тренда по наклону EMA за последние `period` свечей: 'up' / 'down' / 'flat'.
    Используется для тренда старшего ТФ (4ч) в детекторе манипуляции.
    """
    closes = [c["close"] for c in candles]
    if len(closes) < period + 1:
        return "flat"

    ema_values = ema(closes, period)
    slope = ema_values[-1] - ema_values[-period]
    noise_threshold = abs(ema_values[-1]) * 0.001  # 0.1% — отсекаем шум боковика

    if slope > noise_threshold:
        return "up"
    if slope < -noise_threshold:
        return "down"
    return "flat"


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    """
    RSI по методу Уайлдера. Результат той же длины, что и `values` —
    первые `period` элементов None (недостаточно данных), чтобы индекс
    результата совпадал с индексом исходной цены (важно для детектора дивергенции).
    """
    result: list[float | None] = [None] * len(values)
    if len(values) < period + 1:
        return result

    gains = []
    losses = []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result[period] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result[i + 1] = _rsi_from_averages(avg_gain, avg_loss)

    return result


def find_local_peaks(values: list[float], window: int = 3) -> list[int]:
    """Индексы локальных максимумов: значение — максимум в окне ±window вокруг себя."""
    peaks = []
    for i in range(window, len(values) - window):
        segment = values[i - window:i + window + 1]
        if values[i] == max(segment):
            peaks.append(i)
    return peaks


def find_local_troughs(values: list[float], window: int = 3) -> list[int]:
    """Индексы локальных минимумов: значение — минимум в окне ±window вокруг себя."""
    troughs = []
    for i in range(window, len(values) - window):
        segment = values[i - window:i + window + 1]
        if values[i] == min(segment):
            troughs.append(i)
    return troughs


def detect_bearish_divergence(closes: list[float], rsi_values: list, window: int = 3) -> bool:
    """
    Медвежья дивергенция: цена сделала новый хай, а RSI на этом хае — ниже,
    чем на предыдущем хае (ослабление импульса вверх — сигнал разворота вниз).
    """
    peaks = [i for i in find_local_peaks(closes, window) if rsi_values[i] is not None]
    if len(peaks) < 2:
        return False
    i1, i2 = peaks[-2], peaks[-1]
    if closes[i2] <= closes[i1]:
        return False
    return rsi_values[i2] < rsi_values[i1]


def detect_bullish_divergence(closes: list[float], rsi_values: list, window: int = 3) -> bool:
    """
    Бычья дивергенция: цена сделала новый лой, а RSI на этом лое — выше,
    чем на предыдущем лое (ослабление импульса вниз — сигнал разворота вверх).
    """
    troughs = [i for i in find_local_troughs(closes, window) if rsi_values[i] is not None]
    if len(troughs) < 2:
        return False
    i1, i2 = troughs[-2], troughs[-1]
    if closes[i2] >= closes[i1]:
        return False
    return rsi_values[i2] > rsi_values[i1]


def average_volume(candles: list[dict], lookback: int = 20, exclude_last: bool = True) -> float:
    """Средний объём за последние `lookback` свечей (по умолчанию не считая самую последнюю)."""
    series = candles[:-1] if exclude_last and len(candles) > 1 else candles
    series = series[-lookback:]
    if not series:
        return 0.0
    return sum(c["volume"] for c in series) / len(series)


def is_climax_candle(
    candle: dict, avg_volume: float, volume_multiplier: float = 3.0, wick_ratio: float = 0.5
) -> bool:
    """
    True, если у свечи аномально высокий объём (>= volume_multiplier * avg_volume)
    И длинный фитиль-отбой (доля самого длинного фитиля от полного диапазона >= wick_ratio) —
    признак истощения манипулятивного движения (climax reversal).
    """
    if avg_volume <= 0:
        return False
    if candle["volume"] < avg_volume * volume_multiplier:
        return False

    full_range = candle["high"] - candle["low"]
    if full_range <= 0:
        return False

    upper_wick = candle["high"] - max(candle["open"], candle["close"])
    lower_wick = min(candle["open"], candle["close"]) - candle["low"]
    max_wick = max(upper_wick, lower_wick)

    return (max_wick / full_range) >= wick_ratio


def is_funding_extreme(funding_rate: float, threshold: float = 0.001) -> bool:
    """
    True, если funding rate (в долях, 0.0001 = 0.01%) по модулю превышает порог —
    рынок перегружен плечом в одну сторону, повышенный риск сквиза (сигнал разворота).
    """
    return abs(funding_rate) >= threshold


def oi_price_divergence(oi_values: list[float], drop_threshold_pct: float = -5.0) -> bool:
    """
    True, если открытый интерес заметно упал за период (изменение <= drop_threshold_pct,
    отрицательное число) — движение цены объясняется закрытием позиций (сквиз),
    а не притоком нового капитала. Сигнал разворота: сквиз обычно выдыхается.
    """
    if len(oi_values) < 2 or oi_values[0] == 0:
        return False
    oi_change_pct = (oi_values[-1] - oi_values[0]) / oi_values[0] * 100
    return oi_change_pct <= drop_threshold_pct


def calculate_vwap(candles: list[dict]) -> float:
    """Volume-Weighted Average Price по типичной цене (high+low+close)/3 каждой свечи."""
    total_pv = 0.0
    total_v = 0.0
    for c in candles:
        typical_price = (c["high"] + c["low"] + c["close"]) / 3
        total_pv += typical_price * c["volume"]
        total_v += c["volume"]
    if total_v == 0:
        return 0.0
    return total_pv / total_v


def vwap_deviation_pct(candles: list[dict], current_price: float) -> float:
    """
    Отклонение текущей цены от VWAP в %. Большое отклонение — признак того,
    что цена сильно оторвалась от "справедливой" средней (сигнал разворота).
    """
    vwap = calculate_vwap(candles)
    if vwap == 0:
        return 0.0
    return (current_price - vwap) / vwap * 100


def is_near_significant_level(
    candles: list[dict], current_price: float, proximity_pct: float = 1.0, window: int = 3
) -> bool:
    """
    True, если текущая цена находится в пределах proximity_pct% от значимого
    исторического хая/лоя (по свечам старшего ТФ) — цена уткнулась в S/R-уровень,
    сигнал разворота.
    """
    if not candles:
        return False

    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    peak_indices = find_local_peaks(highs, window)
    trough_indices = find_local_troughs(lows, window)
    levels = [highs[i] for i in peak_indices] + [lows[i] for i in trough_indices]

    for level in levels:
        if level == 0:
            continue
        distance_pct = abs(current_price - level) / level * 100
        if distance_pct <= proximity_pct:
            return True
    return False


def atr(candles: list[dict], period: int = 14) -> list[float | None]:
    """
    Average True Range по методу Уайлдера (то же сглаживание, что и rsi()).
    Результат той же длины, что и `candles` — первые `period` элементов None.
    """
    result: list[float | None] = [None] * len(candles)
    if len(candles) < period + 1:
        return result

    true_ranges = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        true_range = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(true_range)

    avg_tr = sum(true_ranges[:period]) / period
    result[period] = avg_tr

    for i in range(period, len(true_ranges)):
        avg_tr = (avg_tr * (period - 1) + true_ranges[i]) / period
        result[i + 1] = avg_tr

    return result
