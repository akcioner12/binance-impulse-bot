import pytest

import trading_storage
import order_executor


def setup_function():
    trading_storage.init_trading_db()
    trading_storage.init_paper_trading_db()


def test_open_paper_position_creates_db_row_and_returns_summary():
    result = order_executor.open_paper_position(
        chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="long",
        fills=[(100.0, 2.0), (98.0, 2.0)],
        sl_method="atr", atr_1h=2.0, atr_multiplier=1.5, fixed_percent=None,
        tp_split_preset="equal",
    )

    assert result["avg_entry_price"] == 99.0  # (100*2 + 98*2) / 4
    assert result["quantity"] == 4.0
    assert result["stop_loss"] == 96.0  # 99 - 1.5*2.0
    assert [tp["size_pct"] for tp in result["take_profits"]] == [25, 25, 25]

    position = trading_storage.get_position(result["position_id"])
    assert position["status"] == "open"
    assert position["avg_entry_price"] == 99.0
    assert position["quantity"] == 4.0


def test_open_paper_position_single_fill():
    result = order_executor.open_paper_position(
        chat_id=111, symbol="ETHUSDT", exchange="Bybit", direction="short",
        fills=[(3000.0, 1.0)],
        sl_method="fixed_percent", atr_1h=None, atr_multiplier=1.5, fixed_percent=4.0,
        tp_split_preset="conservative",
    )

    assert result["avg_entry_price"] == 3000.0
    assert result["stop_loss"] == pytest.approx(3120.0)  # 3000 * 1.04
    assert [tp["size_pct"] for tp in result["take_profits"]] == [40, 30, 20]
