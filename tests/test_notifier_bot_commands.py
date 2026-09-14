import pytest
from unittest.mock import AsyncMock, patch

import notifier


@pytest.mark.asyncio
async def test_set_bot_commands_sets_default_commands_for_everyone():
    with patch("notifier._api_call", new=AsyncMock(return_value={})) as mock_call:
        await notifier.set_bot_commands(None, admin_chat_id=111)

    default_call = next(c for c in mock_call.call_args_list if c.args[2].get("scope") is None)
    method, payload = default_call.args[1], default_call.args[2]
    assert method == "setMyCommands"
    command_names = [c["command"] for c in payload["commands"]]
    assert command_names == ["start", "stop", "status"]
    assert all("command" in c and "description" in c for c in payload["commands"])


@pytest.mark.asyncio
async def test_set_bot_commands_sets_extended_commands_scoped_to_admin_chat():
    with patch("notifier._api_call", new=AsyncMock(return_value={})) as mock_call:
        await notifier.set_bot_commands(None, admin_chat_id=111)

    admin_call = next(c for c in mock_call.call_args_list if c.args[2].get("scope") is not None)
    method, payload = admin_call.args[1], admin_call.args[2]
    assert method == "setMyCommands"
    assert payload["scope"] == {"type": "chat", "chat_id": 111}
    command_names = [c["command"] for c in payload["commands"]]
    assert command_names == ["start", "stop", "status", "trading_setup", "emergency", "reset_paper_balance"]
