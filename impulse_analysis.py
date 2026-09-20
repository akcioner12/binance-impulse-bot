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
    funding_rate = await market_data.fetch_funding_rate(session, exchange, symbol, settled=True)
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


async def build_alert_indicators(session, exchange: str, symbol: str) -> dict | None:
    """
    Доп. показатели для публичного текстового алерта об импульсе (RSI/объём/
    funding/OI) -- легче analyze_impulse() (не тянет 1ч/4ч свечи, они не нужны
    для этих 5 показателей), т.к. вызывается на КАЖДЫЙ алерт КАЖДОМУ подписчику,
    а не только для автотрейдинга владельца.
    """
    candles_15m = await market_data.fetch_klines(session, exchange, symbol, "15m", limit=30)
    if len(candles_15m) < 2:
        return None

    closes = [c["close"] for c in candles_15m]
    rsi_values = indicators.rsi(closes, period=14)
    rsi_value = rsi_values[-1]

    prev_volume = candles_15m[-2]["volume"]
    volume_change_pct = (
        (candles_15m[-1]["volume"] - prev_volume) / prev_volume * 100 if prev_volume > 0 else None
    )

    avg_volume = indicators.average_volume(candles_15m, lookback=20)
    volume_vs_avg_ratio = (candles_15m[-1]["volume"] / avg_volume) if avg_volume > 0 else None

    funding_rate = await market_data.fetch_funding_rate(session, exchange, symbol)

    oi_history = await market_data.fetch_open_interest_history(session, exchange, symbol, period="5m", limit=30)
    oi_values = [row["open_interest"] for row in oi_history]
    oi_change_pct = (
        (oi_values[-1] - oi_values[0]) / oi_values[0] * 100 if len(oi_values) >= 2 and oi_values[0] != 0 else None
    )

    return {
        "rsi": rsi_value,
        "volume_change_pct": volume_change_pct,
        "volume_vs_avg_ratio": volume_vs_avg_ratio,
        "funding_rate": funding_rate,
        "oi_change_pct": oi_change_pct,
    }
