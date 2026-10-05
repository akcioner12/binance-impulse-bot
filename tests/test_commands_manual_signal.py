import pytest
from unittest.mock import AsyncMock, patch

import commands


@pytest.mark.asyncio
async def test_manual_signal_denied_for_non_admin():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.live_trading.handle_channel_signal", new=AsyncMock()) as mock_handle:
        await commands._handle_command(None, 999, "/manual_signal BTW long")

    mock_handle.assert_not_called()


@pytest.mark.asyncio
async def test_manual_signal_calls_handle_channel_signal_with_parsed_args():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.live_trading.handle_channel_signal", new=AsyncMock(return_value={"ok": True})) as mock_handle:
        await commands._handle_command(None, 111, "/manual_signal BTW long")

    mock_handle.assert_called_once_with(None, 111, "BTW", "long", immediate=True)


@pytest.mark.asyncio
async def test_manual_signal_rejects_missing_arguments():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.live_trading.handle_channel_signal", new=AsyncMock()) as mock_handle, \
         patch("commands.send_text") as mock_send:
        await commands._handle_command(None, 111, "/manual_signal BTW")

    mock_handle.assert_not_called()
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_manual_signal_rejects_invalid_direction():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.live_trading.handle_channel_signal", new=AsyncMock()) as mock_handle, \
         patch("commands.send_text") as mock_send:
        await commands._handle_command(None, 111, "/manual_signal BTW sideways")

    mock_handle.assert_not_called()
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_manual_signal_reports_when_signal_rejected():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.live_trading.handle_channel_signal", new=AsyncMock(return_value=None)), \
         patch("commands.send_text") as mock_send:
        await commands._handle_command(None, 111, "/manual_signal BTW long")

    mock_send.assert_called_once()
    assert "не" in mock_send.call_args[0][2].lower()
