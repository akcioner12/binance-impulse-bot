import pytest
from unittest.mock import AsyncMock, patch

import commands


@pytest.mark.asyncio
async def test_reset_paper_balance_command_denied_for_non_admin():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.send_text_with_keyboard", new=AsyncMock()) as mock_send:
        await commands._handle_command(None, 999, "/reset_paper_balance")

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_reset_paper_balance_command_shows_confirm_button():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.send_text_with_keyboard", new=AsyncMock()) as mock_send:
        await commands._handle_command(None, 111, "/reset_paper_balance")

    mock_send.assert_called_once()
    keyboard = mock_send.call_args[0][3]
    callback_data_values = [btn["callback_data"] for row in keyboard for btn in row]
    assert "reset_balance:confirm" in callback_data_values


@pytest.mark.asyncio
async def test_callback_reset_balance_confirm_calls_reset_all_state():
    callback_query = {"id": "cbq-1", "data": "reset_balance:confirm", "message": {"chat": {"id": 111}}}
    with patch("commands.live_trading.reset_all_state") as mock_reset, \
         patch("commands.send_text", new=AsyncMock()) as mock_send_text, \
         patch("commands.answer_callback_query", new=AsyncMock()):
        await commands._handle_callback_query(None, callback_query)

    mock_reset.assert_called_once_with(111, starting_balance=10000.0)
    mock_send_text.assert_called_once()
    assert "10" in mock_send_text.call_args[0][2]
