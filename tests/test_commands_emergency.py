import pytest
from unittest.mock import AsyncMock, patch

import commands


@pytest.mark.asyncio
async def test_emergency_command_denied_for_non_admin():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.send_text_with_keyboard", new=AsyncMock()) as mock_send:
        await commands._handle_command(None, 999, "/emergency")

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_emergency_command_shows_stop_button_when_trading_active():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.trading_storage.get_profile", return_value={"is_active": 1}), \
         patch("commands.send_text_with_keyboard", new=AsyncMock()) as mock_send:
        await commands._handle_command(None, 111, "/emergency")

    mock_send.assert_called_once()
    keyboard = mock_send.call_args[0][3]
    callback_data_values = [btn["callback_data"] for row in keyboard for btn in row]
    assert "emergency:stop" in callback_data_values
    assert "emergency:start" not in callback_data_values
    assert "emergency:close_all" in callback_data_values
    assert "emergency:breakeven_all" in callback_data_values


@pytest.mark.asyncio
async def test_emergency_command_shows_start_button_when_trading_inactive():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.trading_storage.get_profile", return_value={"is_active": 0}), \
         patch("commands.send_text_with_keyboard", new=AsyncMock()) as mock_send:
        await commands._handle_command(None, 111, "/emergency")

    keyboard = mock_send.call_args[0][3]
    callback_data_values = [btn["callback_data"] for row in keyboard for btn in row]
    assert "emergency:start" in callback_data_values
    assert "emergency:stop" not in callback_data_values


@pytest.mark.asyncio
async def test_callback_emergency_stop_calls_stop_trading():
    callback_query = {"id": "cbq-1", "data": "emergency:stop", "message": {"chat": {"id": 111}}}
    with patch("commands.emergency_controls.stop_trading") as mock_stop, \
         patch("commands.send_text", new=AsyncMock()), \
         patch("commands.answer_callback_query", new=AsyncMock()):
        await commands._handle_callback_query(None, callback_query)

    mock_stop.assert_called_once_with(111)


@pytest.mark.asyncio
async def test_callback_emergency_start_calls_start_trading():
    callback_query = {"id": "cbq-2", "data": "emergency:start", "message": {"chat": {"id": 111}}}
    with patch("commands.emergency_controls.start_trading") as mock_start, \
         patch("commands.send_text", new=AsyncMock()), \
         patch("commands.answer_callback_query", new=AsyncMock()):
        await commands._handle_callback_query(None, callback_query)

    mock_start.assert_called_once_with(111)


@pytest.mark.asyncio
async def test_callback_emergency_close_all_reports_closed_symbols():
    callback_query = {"id": "cbq-3", "data": "emergency:close_all", "message": {"chat": {"id": 111}}}
    with patch("commands.emergency_controls.close_all_positions_now", return_value=["BTCUSDT", "ETHUSDT"]), \
         patch("commands.send_text", new=AsyncMock()) as mock_send_text, \
         patch("commands.answer_callback_query", new=AsyncMock()):
        await commands._handle_callback_query(None, callback_query)

    mock_send_text.assert_called_once()
    text = mock_send_text.call_args[0][2]
    assert "BTCUSDT" in text
    assert "ETHUSDT" in text


@pytest.mark.asyncio
async def test_callback_emergency_breakeven_all_reports_updated_symbols():
    callback_query = {"id": "cbq-4", "data": "emergency:breakeven_all", "message": {"chat": {"id": 111}}}
    with patch("commands.emergency_controls.move_all_to_breakeven_plus_now", return_value=["BTCUSDT"]), \
         patch("commands.send_text", new=AsyncMock()) as mock_send_text, \
         patch("commands.answer_callback_query", new=AsyncMock()):
        await commands._handle_callback_query(None, callback_query)

    mock_send_text.assert_called_once()
    assert "BTCUSDT" in mock_send_text.call_args[0][2]


@pytest.mark.asyncio
async def test_callback_emergency_close_all_reports_when_nothing_to_close():
    callback_query = {"id": "cbq-5", "data": "emergency:close_all", "message": {"chat": {"id": 111}}}
    with patch("commands.emergency_controls.close_all_positions_now", return_value=[]), \
         patch("commands.send_text", new=AsyncMock()) as mock_send_text, \
         patch("commands.answer_callback_query", new=AsyncMock()):
        await commands._handle_callback_query(None, callback_query)

    mock_send_text.assert_called_once()
    assert "нет" in mock_send_text.call_args[0][2].lower()
