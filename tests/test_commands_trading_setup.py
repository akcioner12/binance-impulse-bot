import pytest
from unittest.mock import AsyncMock, patch

import commands
import trading_onboarding as ob


def setup_function():
    ob._onboarding.clear()


@pytest.mark.asyncio
async def test_trading_setup_command_calls_start_trading_setup():
    with patch("commands.start_trading_setup", new=AsyncMock()) as mock_start:
        await commands._handle_command(None, 111, "/trading_setup")

    mock_start.assert_called_once_with(None, 111)


@pytest.mark.asyncio
async def test_regular_text_routed_to_onboarding_when_chat_mid_flow():
    ob._onboarding[111] = {"step": "risk_percent", "data": {}}
    with patch("commands.onboarding_handle_text", new=AsyncMock(return_value=True)) as mock_handle:
        await commands._handle_command(None, 111, "1.5")

    mock_handle.assert_called_once_with(None, 111, "1.5")


@pytest.mark.asyncio
async def test_regular_command_not_swallowed_by_onboarding_when_not_in_flow():
    with patch("commands.onboarding_handle_text", new=AsyncMock(return_value=False)) as mock_handle, \
         patch("commands.add_subscriber") as mock_add, \
         patch("commands.send_text", new=AsyncMock()):
        await commands._handle_command(None, 111, "/start")

    mock_handle.assert_called_once()
    mock_add.assert_called_once_with(111)


@pytest.mark.asyncio
async def test_callback_query_dispatched_to_onboarding_handler():
    update = {
        "update_id": 1,
        "callback_query": {
            "id": "cbq-1",
            "data": "trading_setup:defaults",
            "message": {"chat": {"id": 111}},
        },
    }
    with patch("commands._get_updates", new=AsyncMock(side_effect=[[update], []])), \
         patch("commands.onboarding_handle_callback", new=AsyncMock(return_value=True)) as mock_cb, \
         patch("commands.answer_callback_query", new=AsyncMock()) as mock_answer:
        offset = await commands._process_updates_once(None, 0)

    mock_cb.assert_called_once_with(None, 111, "trading_setup:defaults")
    mock_answer.assert_called_once_with(None, "cbq-1")
    assert offset == 2
