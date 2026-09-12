"""
Финальная классификация импульса: разворот (манипуляция, торгуем откат)
или продолжение (движение по тренду, редкий кейс).

По умолчанию — РАЗВОРОТ. ПРОДОЛЖЕНИЕ — только если движение чётко по тренду
старшего ТФ И ни один из остальных 6 сигналов не указывает на разворот.

Эта функция принимает уже посчитанные сигналы, а не сырые данные — расчёт
сигналов (indicators.py) и их сборка из рыночных данных (market_data.py)
происходит в вызывающем коде (оркестратор появится в следующем плане).
"""


def classify_impulse(
    direction: str,
    trend_4h: str,
    relevant_divergence: bool,
    is_climax: bool,
    funding_rate: float,
    oi_diverging: bool,
    near_significant_level: bool,
    vwap_deviation: float,
    funding_extreme_threshold: float = 0.001,
    vwap_extreme_threshold_pct: float = 5.0,
) -> str:
    """
    direction — 'up' или 'down', направление импульса.
    trend_4h — 'up'/'down'/'flat', тренд старшего таймфрейма (indicators.trend_direction).
    relevant_divergence — bearish-дивергенция для 'up'-импульса, bullish — для 'down'
        (вызывающий код сам выбирает нужную из detect_bearish_divergence/detect_bullish_divergence).
    is_climax — indicators.is_climax_candle() на последней свече.
    funding_rate — текущий funding rate в долях (market_data.fetch_funding_rate()).
    oi_diverging — indicators.oi_price_divergence().
    near_significant_level — indicators.is_near_significant_level().
    vwap_deviation — indicators.vwap_deviation_pct(), в процентах.
    """
    trend_aligned = trend_4h == direction
    funding_is_extreme = abs(funding_rate) >= funding_extreme_threshold
    vwap_is_extreme = abs(vwap_deviation) >= vwap_extreme_threshold_pct

    other_reversal_signals = [
        relevant_divergence,
        is_climax,
        funding_is_extreme,
        oi_diverging,
        near_significant_level,
        vwap_is_extreme,
    ]

    if trend_aligned and not any(other_reversal_signals):
        return "continuation"
    return "reversal"
