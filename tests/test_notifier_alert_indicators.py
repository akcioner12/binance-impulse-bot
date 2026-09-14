import pytest
from unittest.mock import AsyncMock, patch

import notifier
from analyzer import ImpulseSignal

SIGNAL = ImpulseSignal(
    symbol="BTCUSDT", exchange="Binance", direction="up", level=30.0,
    change_pct=31.4, window_start_price=100.0, current_price=131.4, is_new_peak=False,
)

FULL_INDICATORS = {
    "rsi": 72.3, "volume_change_pct": 145.0, "volume_vs_avg_ratio": 4.2,
    "funding_rate": 0.00032, "oi_change_pct": 8.5,
}


def test_format_alert_text_without_indicators_unchanged():
    text = notifier._format_alert_text(SIGNAL)
    assert "RSI" not in text
    assert "Объём" not in text
    assert "Funding" not in text
    assert "OI" not in text


def test_format_alert_text_includes_all_indicator_lines():
    text = notifier._format_alert_text(SIGNAL, indicators=FULL_INDICATORS)
    assert "RSI" in text and "72.3" in text
    assert "145.0%" in text  # объём к предыдущей свече
    assert "4.2" in text     # объём к среднему
    assert "0.032%" in text  # funding в процентах
    assert "8.5%" in text    # OI


def test_format_alert_text_skips_missing_indicator_fields():
    partial = {"rsi": 55.0, "volume_change_pct": None, "volume_vs_avg_ratio": None,
               "funding_rate": 0.0001, "oi_change_pct": None}
    text = notifier._format_alert_text(SIGNAL, indicators=partial)
    assert "RSI" in text
    assert "Funding" in text
    assert "Объём" not in text
    assert "OI" not in text


def test_format_alert_text_indicators_none_same_as_omitted():
    assert notifier._format_alert_text(SIGNAL, indicators=None) == notifier._format_alert_text(SIGNAL)


def test_format_alert_text_single_link_by_default():
    text = notifier._format_alert_text(SIGNAL)
    assert text.count("Открыть на") == 1
    assert "Открыть на Binance" in text
    assert "Открыть на Bybit" not in text


def test_format_alert_text_adds_bybit_link_when_also_on_bybit():
    text = notifier._format_alert_text(SIGNAL, also_on_bybit=True)
    assert "Открыть на Binance" in text
    assert "Открыть на Bybit" in text
    assert "bybit.com" in text.lower()


def test_format_alert_text_ignores_also_on_bybit_flag_for_bybit_signal():
    bybit_signal = ImpulseSignal(
        symbol="XUSDT", exchange="Bybit", direction="up", level=30.0,
        change_pct=31.4, window_start_price=1.0, current_price=1.3, is_new_peak=False,
    )
    text = notifier._format_alert_text(bybit_signal, also_on_bybit=True)
    assert text.count("Открыть на") == 1  # сигнал уже с Bybit -- второй ссылки на Bybit не нужно


@pytest.mark.asyncio
async def test_send_or_edit_alert_passes_indicators_into_text():
    with patch("notifier.get_message_id", return_value=None), \
         patch("notifier.set_message_id"), \
         patch("notifier._api_call", new=AsyncMock(return_value={"message_id": 1})) as mock_call:
        await notifier.send_or_edit_alert(None, 111, SIGNAL, indicators=FULL_INDICATORS)

    payload = mock_call.call_args[0][2]
    assert "RSI" in payload["text"]
