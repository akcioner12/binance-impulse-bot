import pytest
from unittest.mock import AsyncMock, patch

import commands


@pytest.mark.asyncio
async def test_subscribers_command_denied_for_non_admin():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.send_text", new=AsyncMock()) as mock_send:
        await commands._handle_command(None, 999, "/subscribers")

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_subscribers_command_reports_none_when_empty():
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.get_all_subscribers", return_value=[]), \
         patch("commands.send_text", new=AsyncMock()) as mock_send:
        await commands._handle_command(None, 111, "/subscribers")

    mock_send.assert_called_once()
    assert "нет" in mock_send.call_args[0][2].lower()


@pytest.mark.asyncio
async def test_subscribers_command_lists_chat_ids_with_resolved_usernames():
    chat_infos = {
        111111: {"id": 111111, "username": "ivan", "first_name": "Иван"},
        222222: {"id": 222222, "first_name": "Пётр"},  # без username
        333333: None,  # getChat не удался (например, юзер заблокировал бота)
    }
    with patch("commands.ADMIN_CHAT_ID", 111), \
         patch("commands.get_all_subscribers", return_value=[111111, 222222, 333333]), \
         patch("commands.get_chat_info", new=AsyncMock(side_effect=lambda s, cid: chat_infos[cid])), \
         patch("commands.send_text", new=AsyncMock()) as mock_send:
        await commands._handle_command(None, 111, "/subscribers")

    mock_send.assert_called_once()
    text = mock_send.call_args[0][2]
    assert "111111" in text and "@ivan" in text
    assert "222222" in text and "Пётр" in text
    assert "333333" in text
    assert "3" in text  # общее число подписчиков в заголовке


def test_format_subscriber_line_escapes_markdown_special_chars_in_username():
    """
    Прод-баг 14.09.2026: юзернейм с "_" ломал парсинг Markdown у Telegram
    ("can't parse entities: Can't find end of the entity...") -- вся команда
    молча падала на отправке, без единого сообщения админу.
    """
    line = commands._format_subscriber_line(111111, {"id": 111111, "username": "john_doe_123"})
    assert "john\\_doe\\_123" in line


def test_format_subscriber_line_escapes_markdown_special_chars_in_name():
    line = commands._format_subscriber_line(222222, {"id": 222222, "first_name": "Ivan_*test"})
    assert "Ivan\\_\\*test" in line
