import pytest
from unittest.mock import AsyncMock, patch

import trade_signal_ux

ANALYSIS = {"classification": "reversal", "atr_15m": 1.0, "atr_1h": 2.0}
PROFILE = {"is_active": 1}


async def _announce(execute_fn, **overrides):
    kwargs = dict(
        session=None, chat_id=111, symbol="BTCUSDT", exchange="Binance", direction="up",
        classification="reversal", current_price=100.0, window_start_price=76.0,
        profile=PROFILE, analysis=ANALYSIS, signal_id=55, magnet_levels=[150.0, 200.0],
        execute_fn=execute_fn,
    )
    kwargs.update(overrides)
    await trade_signal_ux.announce_and_execute(**kwargs)


@pytest.mark.asyncio
async def test_setup_is_executed_immediately_with_all_arguments():
    """
    20.09.2026: подтверждение кнопкой и 5-минутное ожидание убраны -- за 5 минут
    манипуляция уже успевает развиться, а профиль и так полностью настроен.
    """
    execute_fn = AsyncMock()
    with patch("trade_signal_ux.send_text", new=AsyncMock()):
        await _announce(execute_fn)

    execute_fn.assert_awaited_once()
    args = execute_fn.call_args[0]
    assert args[1:6] == (111, "BTCUSDT", "Binance", "up", "reversal")
    assert args[6:8] == (100.0, 76.0)
    assert args[10] == 55  # signal_id


@pytest.mark.asyncio
async def test_announcement_is_plain_text_without_buttons_and_mentions_automatic_entry():
    with patch("trade_signal_ux.send_text", new=AsyncMock()) as mock_send:
        await _announce(AsyncMock())

    mock_send.assert_awaited_once()
    text = mock_send.call_args[0][2]
    assert "BTCUSDT" in text and "150" in text
    assert "автоматически" in text
    assert not hasattr(trade_signal_ux, "send_text_with_keyboard")


@pytest.mark.asyncio
async def test_execution_error_is_reported_to_admin_and_not_raised():
    """Прод-инцидент 14.09.2026: сбой в execute_fn не должен теряться молча."""
    async def failing_execute_fn(*args):
        raise RuntimeError("boom")

    with patch("trade_signal_ux.send_text", new=AsyncMock()) as mock_send:
        await _announce(failing_execute_fn)  # не должно упасть

    mock_send.assert_awaited_once()
    assert mock_send.call_args[0][1] == 111
    assert "BTCUSDT" in mock_send.call_args[0][2] and "boom" in mock_send.call_args[0][2]


def test_confirmation_machinery_is_gone():
    for name in ("request_confirmation", "handle_confirmation_callback", "is_awaiting_confirmation",
                 "_awaiting_confirmation", "CONFIRMATION_TIMEOUT_SECONDS"):
        assert not hasattr(trade_signal_ux, name)
