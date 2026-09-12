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
