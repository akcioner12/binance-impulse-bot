import pytest
from unittest.mock import AsyncMock, patch

import commands


@pytest.mark.asyncio
async def test_stale_trade_confirm_button_from_old_message_is_ignored_safely():
    """
    Кнопки подтверждения сетапа убраны (20.09.2026), но в чате остались старые
    сообщения с ними -- нажатие не должно ронять обработчик и не должно ничего исполнять.
    """
    callback_query = {"id": "cbq-1", "data": "trade_confirm:defaults:BTCUSDT", "message": {"chat": {"id": 111}}}
    with patch("commands.onboarding_handle_callback", new=AsyncMock(return_value=False)) as mock_onboarding, \
         patch("commands.answer_callback_query", new=AsyncMock()) as mock_answer:
        await commands._handle_callback_query(None, callback_query)

    mock_onboarding.assert_awaited_once()
    mock_answer.assert_awaited_once_with(None, "cbq-1")
