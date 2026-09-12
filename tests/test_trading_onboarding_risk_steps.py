import pytest
from unittest.mock import AsyncMock, patch

import trading_onboarding as ob
import trading_storage


def setup_function():
    trading_storage.init_trading_db()
    ob._onboarding.clear()


@pytest.mark.asyncio
async def test_sl_method_atr_skips_fixed_percent_step():
    ob._onboarding[111] = {
        "step": "sl_method",
        "data": {"risk_percent": 1.0, "daily_loss_limit_percent": 5.0, "leverage": 3.0},
    }
    with patch("trading_onboarding.send_text", new=AsyncMock()):
        handled = await ob.handle_callback(None, 111, "sl_method:atr")

    assert handled is True
    assert ob._onboarding[111]["data"]["sl_method"] == "atr"
    assert ob._onboarding[111]["data"]["sl_fixed_percent"] is None
    assert ob._onboarding[111]["step"] == "breakeven_after_tp"


@pytest.mark.asyncio
async def test_sl_method_fixed_asks_for_percent():
    ob._onboarding[111] = {
        "step": "sl_method",
        "data": {"risk_percent": 1.0, "daily_loss_limit_percent": 5.0, "leverage": 3.0},
    }
    with patch("trading_onboarding.send_text", new=AsyncMock()):
        handled = await ob.handle_callback(None, 111, "sl_method:fixed")

    assert handled is True
    assert ob._onboarding[111]["step"] == "sl_fixed_percent"


@pytest.mark.asyncio
async def test_sl_fixed_percent_step_saves_and_advances():
    ob._onboarding[111] = {
        "step": "sl_fixed_percent",
        "data": {"risk_percent": 1.0, "daily_loss_limit_percent": 5.0, "leverage": 3.0, "sl_method": "fixed_percent"},
    }
    with patch("trading_onboarding.send_text", new=AsyncMock()):
        handled = await ob.handle_text(None, 111, "4")

    assert handled is True
    assert ob._onboarding[111]["data"]["sl_fixed_percent"] == 4.0
    assert ob._onboarding[111]["step"] == "breakeven_after_tp"


@pytest.mark.asyncio
async def test_breakeven_after_tp_step_saves_and_advances():
    ob._onboarding[111] = {
        "step": "breakeven_after_tp",
        "data": {"risk_percent": 1.0, "daily_loss_limit_percent": 5.0, "leverage": 3.0,
                  "sl_method": "atr", "sl_fixed_percent": None},
    }
    with patch("trading_onboarding.send_text_with_keyboard", new=AsyncMock()):
        handled = await ob.handle_text(None, 111, "2")

    assert handled is True
    assert ob._onboarding[111]["data"]["breakeven_after_tp"] == 2
    assert ob._onboarding[111]["step"] == "tp_split_preset"


@pytest.mark.asyncio
async def test_breakeven_after_tp_rejects_non_integer():
    ob._onboarding[111] = {"step": "breakeven_after_tp", "data": {}}
    with patch("trading_onboarding.send_text", new=AsyncMock()) as mock_send:
        handled = await ob.handle_text(None, 111, "два")

    assert handled is True
    assert ob._onboarding[111]["step"] == "breakeven_after_tp"
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_tp_split_preset_with_safe_values_goes_straight_to_exchange_choice():
    ob._onboarding[111] = {
        "step": "tp_split_preset",
        "data": {
            "risk_percent": 1.0, "daily_loss_limit_percent": 5.0, "leverage": 3.0,
            "sl_method": "atr", "sl_fixed_percent": None, "breakeven_after_tp": 2,
        },
    }
    with patch("trading_onboarding.send_text_with_keyboard", new=AsyncMock()):
        handled = await ob.handle_callback(None, 111, "tp_split:equal")

    assert handled is True
    profile = trading_storage.get_profile(111)
    assert profile is not None
    assert profile["tp_split_preset"] == "equal"
    assert ob._onboarding[111]["step"] == "exchange_choice"


@pytest.mark.asyncio
async def test_tp_split_preset_with_risky_values_shows_warning():
    ob._onboarding[222] = {
        "step": "tp_split_preset",
        "data": {
            "risk_percent": 5.0,  # выше порога 3.0 — должно предупредить
            "daily_loss_limit_percent": 5.0, "leverage": 3.0,
            "sl_method": "atr", "sl_fixed_percent": None, "breakeven_after_tp": 2,
        },
    }
    with patch("trading_onboarding.send_text_with_keyboard", new=AsyncMock()) as mock_send:
        handled = await ob.handle_callback(None, 222, "tp_split:equal")

    assert handled is True
    assert ob._onboarding[222]["step"] == "risk_warning_confirm"
    assert trading_storage.get_profile(222) is None  # ещё не сохранено
    mock_send.assert_called_once()
    text = mock_send.call_args[0][2]
    assert "риск" in text.lower()


@pytest.mark.asyncio
async def test_risk_warning_keep_mine_saves_original_values():
    ob._onboarding[222] = {
        "step": "risk_warning_confirm",
        "data": {
            "risk_percent": 5.0, "daily_loss_limit_percent": 5.0, "leverage": 3.0,
            "sl_method": "atr", "sl_fixed_percent": None, "breakeven_after_tp": 2,
            "tp_split_preset": "equal",
        },
    }
    with patch("trading_onboarding.send_text_with_keyboard", new=AsyncMock()):
        handled = await ob.handle_callback(None, 222, "risk_warn:keep_mine")

    assert handled is True
    profile = trading_storage.get_profile(222)
    assert profile["risk_percent"] == 5.0
    assert ob._onboarding[222]["step"] == "exchange_choice"


@pytest.mark.asyncio
async def test_risk_warning_apply_recommended_clamps_flagged_fields():
    ob._onboarding[222] = {
        "step": "risk_warning_confirm",
        "data": {
            "risk_percent": 5.0, "daily_loss_limit_percent": 5.0, "leverage": 15.0,
            "sl_method": "atr", "sl_fixed_percent": None, "breakeven_after_tp": 2,
            "tp_split_preset": "equal",
        },
    }
    with patch("trading_onboarding.send_text_with_keyboard", new=AsyncMock()):
        handled = await ob.handle_callback(None, 222, "risk_warn:apply_recommended")

    assert handled is True
    profile = trading_storage.get_profile(222)
    assert profile["risk_percent"] == ob.RISK_WARNING_THRESHOLDS["risk_percent"]
    assert profile["leverage"] == ob.RISK_WARNING_THRESHOLDS["leverage"]
    assert profile["daily_loss_limit_percent"] == 5.0  # не флагован, не тронут
