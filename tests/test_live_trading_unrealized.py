import order_executor
import live_trading


def setup_function():
    live_trading._pending_setups.clear()
    live_trading._open_positions.clear()
    live_trading._notification_queue.clear()
    live_trading._last_prices.clear()


def _open(symbol, direction, entry, qty, remaining=None):
    if direction == "long":
        sl, tps = entry * 0.9, [{"level": entry * 1.5, "size_pct": 25}, {"level": entry * 1.6, "size_pct": 25}, {"level": entry * 1.7, "size_pct": 25}]
    else:
        sl, tps = entry * 1.1, [{"level": entry * 0.5, "size_pct": 25}, {"level": entry * 0.4, "size_pct": 25}, {"level": entry * 0.3, "size_pct": 25}]
    state = order_executor.OpenPositionState(1, direction, entry, qty, sl, tps, 2)
    if remaining is not None:
        state.remaining_quantity = remaining
    live_trading._open_positions[symbol] = {"chat_id": 111, "state": state, "atr_1h": 2.0}
    return state


def test_unrealized_pnl_long_uses_last_tick_price_and_remaining_quantity():
    _open("BTCUSDT", "long", 100.0, 4.0, remaining=3.0)
    live_trading.handle_price_tick("BTCUSDT", price=105.0)

    pnl, count = live_trading.get_unrealized_pnl(111)

    assert count == 1
    assert pnl == 15.0  # 3.0 * (105 - 100)


def test_unrealized_pnl_short_is_positive_when_price_falls():
    _open("ETHUSDT", "short", 100.0, 4.0)
    live_trading.handle_price_tick("ETHUSDT", price=95.0)

    assert live_trading.get_unrealized_pnl(111) == (20.0, 1)


def test_unrealized_pnl_sums_positions_and_ignores_other_chats():
    _open("BTCUSDT", "long", 100.0, 1.0)
    _open("ETHUSDT", "short", 100.0, 1.0)
    live_trading._open_positions["ETHUSDT"]["chat_id"] = 222
    live_trading.handle_price_tick("BTCUSDT", price=102.0)
    live_trading.handle_price_tick("ETHUSDT", price=90.0)

    assert live_trading.get_unrealized_pnl(111) == (2.0, 1)


def test_position_without_any_tick_counts_as_open_with_zero_pnl():
    _open("BTCUSDT", "long", 100.0, 4.0)

    assert live_trading.get_unrealized_pnl(111) == (0.0, 1)
