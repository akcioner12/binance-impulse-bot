import pytest
from unittest.mock import patch

import commands


@pytest.mark.asyncio
async def test_set_max_trades_denied_for_non_admin():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.trading_storage.update_max_concurrent_trades") as mock_update:
        await commands._handle_command(None, 999, "/set_max_trades 10")

    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_set_max_trades_updates_profile_and_confirms():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.trading_storage.update_max_concurrent_trades") as mock_update, \
         patch("commands.send_text") as mock_send:
        await commands._handle_command(None, 111, "/set_max_trades 10")

    mock_update.assert_called_once_with(111, 10)
    mock_send.assert_called_once()
    assert "10" in mock_send.call_args[0][2]


@pytest.mark.asyncio
async def test_set_max_trades_rejects_missing_argument():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.trading_storage.update_max_concurrent_trades") as mock_update, \
         patch("commands.send_text") as mock_send:
        await commands._handle_command(None, 111, "/set_max_trades")

    mock_update.assert_not_called()
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_set_max_trades_rejects_non_positive_value():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.trading_storage.update_max_concurrent_trades") as mock_update, \
         patch("commands.send_text") as mock_send:
        await commands._handle_command(None, 111, "/set_max_trades 0")

    mock_update.assert_not_called()
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_set_max_trades_rejects_non_numeric_argument():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.trading_storage.update_max_concurrent_trades") as mock_update, \
         patch("commands.send_text") as mock_send:
        await commands._handle_command(None, 111, "/set_max_trades abc")

    mock_update.assert_not_called()
    mock_send.assert_called_once()
