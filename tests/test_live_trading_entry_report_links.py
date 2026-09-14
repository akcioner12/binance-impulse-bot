import live_trading

SNAPSHOT = {
    "chat_id": 111, "direction": "long", "avg_entry_price": 0.10298, "quantity": 34713.2,
    "stop_loss": 0.0943377, "take_profits": [{"level": 0.111622, "size_pct": 15}],
    "tp4_size_pct": 85, "risk_amount": 300.0,
}


def test_format_entry_report_single_link_by_default():
    text = live_trading.format_entry_report("AINUSDT", "Binance", SNAPSHOT)
    assert text.count("Открыть на") == 1
    assert "Открыть на Binance" in text
    assert "Открыть на Bybit" not in text


def test_format_entry_report_adds_bybit_link_when_also_on_bybit():
    text = live_trading.format_entry_report("AINUSDT", "Binance", SNAPSHOT, also_on_bybit=True)
    assert "Открыть на Binance" in text
    assert "Открыть на Bybit" in text
    assert "bybit.com" in text.lower()


def test_format_entry_report_ignores_flag_for_bybit_source():
    text = live_trading.format_entry_report("XUSDT", "Bybit", SNAPSHOT, also_on_bybit=True)
    assert text.count("Открыть на") == 1
