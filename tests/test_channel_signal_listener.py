import inspect

import pytest
from unittest.mock import AsyncMock, patch

import channel_signal_listener
from channel_signal_listener import on_channel_message


@pytest.mark.asyncio
async def test_on_channel_message_dispatches_recognized_signal():
    text = "ЗАХОДИМ В МАНИПУЛЯЦИЮ\n\nXAI SHORT  - текст"
    with patch("channel_signal_listener.ADMIN_CHAT_ID", 111), \
         patch("channel_signal_listener.live_trading.handle_channel_signal", new=AsyncMock(
             return_value={"classification": "reversal", "signal_id": 1}
         )) as mock_handle:
        result = await on_channel_message(session=None, text=text)
    mock_handle.assert_called_once_with(None, 111, "XAI", "short")
    assert result == {"classification": "reversal", "signal_id": 1}


@pytest.mark.asyncio
async def test_on_channel_message_none_for_unrecognized_text():
    with patch("channel_signal_listener.live_trading.handle_channel_signal", new=AsyncMock()) as mock_handle:
        result = await on_channel_message(session=None, text="СДЕЛКА НА СПОТ\n\nUAI Long беру от текущих")
    mock_handle.assert_not_called()
    assert result is None


@pytest.mark.asyncio
async def test_on_channel_message_none_for_missing_text():
    with patch("channel_signal_listener.live_trading.handle_channel_signal", new=AsyncMock()) as mock_handle:
        result = await on_channel_message(session=None, text=None)
    mock_handle.assert_not_called()
    assert result is None


def test_listener_reads_raw_text_not_markdown_formatted_text():
    """
    Критично: Telethon Message.text возвращает текст, отформатированный markdown'ом
    клиента по умолчанию (жирный заголовок/тикер ломает парсер типа A/B). Нужно
    читать raw_text -- см. код-ревью финальной ветки.
    """
    source = inspect.getsource(channel_signal_listener.run_channel_signal_listener)
    assert "raw_text" in source
    assert "event.message.text" not in source


def test_listener_does_not_call_blocking_interactive_start():
    """
    client.start() на Railway без валидной сессии падает в интерактивный
    input() за номером телефона -- либо EOFError, либо (если stdin открыт)
    блокировка всего event loop. Листенер должен сам проверять авторизацию
    (is_user_authorized) и не вызывать start().
    """
    source = inspect.getsource(channel_signal_listener.run_channel_signal_listener)
    assert "is_user_authorized" in source
    assert "client.start()" not in source
