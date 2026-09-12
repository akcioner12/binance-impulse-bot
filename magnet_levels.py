"""
Лесенка магнит-уровней: докуда манипулятивное движение вероятно дотянет,
прежде чем развернётся. Ближний/средний уровень ищутся по дневным свечам,
дальний — по недельным (более широкий охват истории для структурных уровней).
"""

import indicators


def _extract_levels(candles: list[dict], current_price: float, direction: str, window: int) -> list[float]:
    """Уровни, отсортированные по возрастанию расстояния от current_price (ближний первый)."""
    if direction == "up":
        highs = [c["high"] for c in candles]
        indices = indicators.find_local_peaks(highs, window)
        candidates = sorted({highs[i] for i in indices if highs[i] > current_price})
    else:
        lows = [c["low"] for c in candles]
        indices = indicators.find_local_troughs(lows, window)
        candidates = sorted({lows[i] for i in indices if lows[i] < current_price}, reverse=True)
    return candidates


def find_magnet_levels(
    daily_candles: list[dict],
    weekly_candles: list[dict],
    current_price: float,
    direction: str,
    window: int = 3,
) -> list[float]:
    """
    direction — 'up' (ищем уровни-сопротивления выше цены) или 'down' (уровни-поддержки ниже).
    Возвращает до 3 уровней: 2 ближайших с дневных свечей (ближний/средний) +
    1 самый дальний с недельных (структурный дальний уровень), по возрастанию расстояния.
    """
    daily_levels = _extract_levels(daily_candles, current_price, direction, window)
    weekly_levels = _extract_levels(weekly_candles, current_price, direction, window)

    near_mid = daily_levels[:2]
    far_candidates = [lvl for lvl in weekly_levels if lvl not in near_mid]
    far = far_candidates[-1:] if far_candidates else []

    return near_mid + far
