import pytest
from unittest.mock import patch

import commands


@pytest.mark.asyncio
async def test_close_position_denied_for_non_admin():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.emergency_controls.close_position_now") as mock_close:
        await commands._handle_command(None, 999, "/close_position KOMAUSDT")

    mock_close.assert_not_called()


@pytest.mark.asyncio
async def test_close_position_closes_and_confirms():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.emergency_controls.close_position_now", return_value=True) as mock_close, \
         patch("commands.send_text") as mock_send:
        await commands._handle_command(None, 111, "/close_position KOMAUSDT")

    mock_close.assert_called_once_with(111, "KOMAUSDT")
    mock_send.assert_called_once()
    assert "KOMAUSDT" in mock_send.call_args[0][2]


@pytest.mark.asyncio
async def test_close_position_reports_when_symbol_not_open():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.emergency_controls.close_position_now", return_value=False), \
         patch("commands.send_text") as mock_send:
        await commands._handle_command(None, 111, "/close_position KOMAUSDT")

    mock_send.assert_called_once()
    assert "нет" in mock_send.call_args[0][2].lower() or "не найдена" in mock_send.call_args[0][2].lower()


@pytest.mark.asyncio
async def test_close_position_rejects_missing_argument():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.emergency_controls.close_position_now") as mock_close, \
         patch("commands.send_text") as mock_send:
        await commands._handle_command(None, 111, "/close_position")

    mock_close.assert_not_called()
    mock_send.assert_called_once()
