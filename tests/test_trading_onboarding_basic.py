import pytest
from unittest.mock import AsyncMock, patch

import trading_onboarding as ob
import trading_storage


def setup_function():
    trading_storage.init_trading_db()
    ob._onboarding.clear()


@pytest.mark.asyncio
async def test_start_trading_setup_sends_two_buttons():
    with patch("trading_onboarding.send_text_with_keyboard", new=AsyncMock()) as mock_send:
        await ob.start_trading_setup(None, 111)

    mock_send.assert_called_once()
    args, kwargs = mock_send.call_args
    keyboard = args[3]
    callback_data_values = [btn["callback_data"] for row in keyboard for btn in row]
    assert "trading_setup:defaults" in callback_data_values
    assert "trading_setup:manual" in callback_data_values


@pytest.mark.asyncio
async def test_defaults_callback_saves_default_profile_and_asks_exchange_choice():
    with patch("trading_onboarding.send_text_with_keyboard", new=AsyncMock()) as mock_send_kb:
        handled = await ob.handle_callback(None, 111, "trading_setup:defaults")

    assert handled is True
    profile = trading_storage.get_profile(111)
    assert profile["risk_percent"] == ob.DEFAULT_PROFILE["risk_percent"]
    assert profile["leverage"] == ob.DEFAULT_PROFILE["leverage"]
    assert profile["daily_loss_limit_percent"] == ob.DEFAULT_PROFILE["daily_loss_limit_percent"]
    assert profile["max_concurrent_trades"] == ob.DEFAULT_PROFILE["max_concurrent_trades"]
    # После дефолтов сразу переходим к выбору биржи (юзер сам решает, с какой начать)
    assert ob._onboarding[111]["step"] == "exchange_choice"
    mock_send_kb.assert_called_once()


@pytest.mark.asyncio
async def test_manual_callback_starts_step_flow():
    with patch("trading_onboarding.send_text", new=AsyncMock()):
        handled = await ob.handle_callback(None, 222, "trading_setup:manual")

    assert handled is True
    assert ob._onboarding[222]["step"] == "risk_percent"


@pytest.mark.asyncio
async def test_risk_percent_step_saves_value_and_advances():
    ob._onboarding[333] = {"step": "risk_percent", "data": {}}
    with patch("trading_onboarding.send_text", new=AsyncMock()):
        handled = await ob.handle_text(None, 333, "1.5")

    assert handled is True
    assert ob._onboarding[333]["data"]["risk_percent"] == 1.5
    assert ob._onboarding[333]["step"] == "daily_loss_limit_percent"


@pytest.mark.asyncio
async def test_risk_percent_step_rejects_non_numeric_input():
    ob._onboarding[333] = {"step": "risk_percent", "data": {}}
    with patch("trading_onboarding.send_text", new=AsyncMock()) as mock_send:
        handled = await ob.handle_text(None, 333, "не число")

    assert handled is True
    assert ob._onboarding[333]["step"] == "risk_percent"  # шаг не продвинулся
    mock_send.assert_called_once()
    assert "цифр" in mock_send.call_args[0][2].lower()


@pytest.mark.asyncio
async def test_daily_loss_limit_step_saves_value_and_advances():
    ob._onboarding[333] = {"step": "daily_loss_limit_percent", "data": {"risk_percent": 1.0}}
    with patch("trading_onboarding.send_text", new=AsyncMock()):
        handled = await ob.handle_text(None, 333, "5")

    assert handled is True
    assert ob._onboarding[333]["data"]["daily_loss_limit_percent"] == 5.0
    assert ob._onboarding[333]["step"] == "leverage"


@pytest.mark.asyncio
async def test_leverage_step_saves_value_and_advances():
    ob._onboarding[333] = {
        "step": "leverage",
        "data": {"risk_percent": 1.0, "daily_loss_limit_percent": 5.0},
    }
    with patch("trading_onboarding.send_text_with_keyboard", new=AsyncMock()):
        handled = await ob.handle_text(None, 333, "3")

    assert handled is True
    assert ob._onboarding[333]["data"]["leverage"] == 3.0
    assert ob._onboarding[333]["step"] == "sl_method"


@pytest.mark.asyncio
async def test_handle_text_returns_false_when_chat_not_in_onboarding():
    handled = await ob.handle_text(None, 999, "любой текст")
    assert handled is False


@pytest.mark.asyncio
async def test_handle_callback_returns_false_for_unknown_callback():
    handled = await ob.handle_callback(None, 999, "unrelated:callback")
    assert handled is False
