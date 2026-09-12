"""
Оркестратор анализа импульса: собирает все 7 сигналов детектора манипуляции
из рыночных данных и возвращает готовую классификацию.

Распределение таймфреймов по сигналам:
- 15м: RSI/дивергенция, объёмный climax (самое быстрое разрешение —
  ловит признаки истощения рано)
- 1ч: VWAP-отклонение (усреднение за разумное окно)
- 4ч: тренд, близость к S/R-уровню ("старший ТФ" по спеке)
"""

import market_data
import indicators
import manipulation_detector


async def analyze_impulse(
    session, symbol: str, exchange: str, direction: str, current_price: float
) -> dict:
    """
    direction — 'up' или 'down', направление импульса (из analyzer.ImpulseSignal.direction).
    current_price — текущая цена (из analyzer.ImpulseSignal.current_price).
    """
    candles_15m = await market_data.fetch_klines(session, exchange, symbol, "15m", limit=50)
    candles_1h = await market_data.fetch_klines(session, exchange, symbol, "1h", limit=24)
    candles_4h = await market_data.fetch_klines(session, exchange, symbol, "4h", limit=30)
    funding_rate = await market_data.fetch_funding_rate(session, exchange, symbol)
    oi_history = await market_data.fetch_open_interest_history(session, exchange, symbol, period="5m", limit=30)

    trend_4h = indicators.trend_direction(candles_4h, period=20)

    closes_15m = [c["close"] for c in candles_15m]
    rsi_values = indicators.rsi(closes_15m, period=14)
    if direction == "up":
        relevant_divergence = indicators.detect_bearish_divergence(closes_15m, rsi_values)
    else:
        relevant_divergence = indicators.detect_bullish_divergence(closes_15m, rsi_values)

    if candles_15m:
        avg_volume_15m = indicators.average_volume(candles_15m, lookback=20)
        is_climax = indicators.is_climax_candle(candles_15m[-1], avg_volume_15m)
    else:
        is_climax = False

    oi_values = [row["open_interest"] for row in oi_history]
    oi_diverging = indicators.oi_price_divergence(oi_values)

    near_significant_level = indicators.is_near_significant_level(candles_4h, current_price)

    vwap_deviation = indicators.vwap_deviation_pct(candles_1h, current_price)

    atr_15m_values = indicators.atr(candles_15m, period=14)
    atr_15m = atr_15m_values[-1] if atr_15m_values else None

    atr_1h_values = indicators.atr(candles_1h, period=14)
    atr_1h = atr_1h_values[-1] if atr_1h_values else None

    classification = manipulation_detector.classify_impulse(
        direction=direction,
        trend_4h=trend_4h,
        relevant_divergence=relevant_divergence,
        is_climax=is_climax,
        funding_rate=funding_rate,
        oi_diverging=oi_diverging,
        near_significant_level=near_significant_level,
        vwap_deviation=vwap_deviation,
    )

    return {
        "classification": classification,
        "trend_4h": trend_4h,
        "relevant_divergence": relevant_divergence,
        "is_climax": is_climax,
        "funding_rate": funding_rate,
        "oi_diverging": oi_diverging,
        "near_significant_level": near_significant_level,
        "vwap_deviation": vwap_deviation,
        "atr_15m": atr_15m,
        "atr_1h": atr_1h,
    }
