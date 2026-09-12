import pytest
from unittest.mock import AsyncMock, patch

import notifier


@pytest.mark.asyncio
async def test_send_text_with_keyboard_calls_send_message_with_reply_markup():
    keyboard = [[{"text": "Кнопка", "callback_data": "test:action"}]]
    with patch("notifier._api_call", new=AsyncMock(return_value={"message_id": 42})) as mock_call:
        result = await notifier.send_text_with_keyboard(None, 111, "Текст", keyboard)

    mock_call.assert_called_once()
    args, kwargs = mock_call.call_args
    method = args[1]
    payload = args[2]
    assert method == "sendMessage"
    assert payload["chat_id"] == 111
    assert payload["text"] == "Текст"
    assert payload["reply_markup"] == {"inline_keyboard": keyboard}
    assert result == {"message_id": 42}


@pytest.mark.asyncio
async def test_answer_callback_query_calls_api():
    with patch("notifier._api_call", new=AsyncMock(return_value={})) as mock_call:
        await notifier.answer_callback_query(None, "callback-id-123")

    mock_call.assert_called_once()
    args, kwargs = mock_call.call_args
    method = args[1]
    payload = args[2]
    assert method == "answerCallbackQuery"
    assert payload["callback_query_id"] == "callback-id-123"
