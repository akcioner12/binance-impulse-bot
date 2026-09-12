import pytest
from unittest.mock import AsyncMock, patch

import commands


@pytest.mark.asyncio
async def test_callback_query_trade_confirm_routed_to_trade_signal_ux():
    callback_query = {
        "id": "cbq-1",
        "data": "trade_confirm:defaults:BTCUSDT",
        "message": {"chat": {"id": 111}},
    }
    with patch("commands.trade_signal_ux.handle_confirmation_callback", new=AsyncMock(return_value=True)) as mock_confirm, \
         patch("commands.onboarding_handle_callback", new=AsyncMock()) as mock_onboarding, \
         patch("commands.answer_callback_query", new=AsyncMock()) as mock_answer:
        await commands._handle_callback_query(None, callback_query)

    mock_confirm.assert_called_once_with("BTCUSDT", "defaults")
    mock_onboarding.assert_not_called()
    mock_answer.assert_called_once_with(None, "cbq-1")


@pytest.mark.asyncio
async def test_callback_query_non_trade_confirm_still_routed_to_onboarding():
    callback_query = {
        "id": "cbq-2",
        "data": "trading_setup:defaults",
        "message": {"chat": {"id": 111}},
    }
    with patch("commands.trade_signal_ux.handle_confirmation_callback", new=AsyncMock()) as mock_confirm, \
         patch("commands.onboarding_handle_callback", new=AsyncMock(return_value=True)) as mock_onboarding, \
         patch("commands.answer_callback_query", new=AsyncMock()):
        await commands._handle_callback_query(None, callback_query)

    mock_confirm.assert_not_called()
    mock_onboarding.assert_called_once_with(None, 111, "trading_setup:defaults")
