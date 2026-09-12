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
