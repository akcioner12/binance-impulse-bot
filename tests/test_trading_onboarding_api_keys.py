import pytest
from unittest.mock import AsyncMock, patch

import trading_onboarding as ob
import trading_storage


def setup_function():
    trading_storage.init_trading_db()
    trading_storage.init_paper_trading_db()
    ob._onboarding.clear()


@pytest.mark.asyncio
async def test_api_binance_key_step_saves_and_asks_secret():
    ob._onboarding[111] = {"step": "api_binance_key", "data": {}}
    with patch("trading_onboarding.send_text", new=AsyncMock()):
        handled = await ob.handle_text(None, 111, "my-binance-key")

    assert handled is True
    assert ob._onboarding[111]["data"]["binance_api_key"] == "my-binance-key"
    assert ob._onboarding[111]["step"] == "api_binance_secret"


@pytest.mark.asyncio
async def test_api_binance_secret_step_saves_credentials_and_asks_about_bybit():
    ob._onboarding[111] = {
        "step": "api_binance_secret",
        "data": {"binance_api_key": "my-binance-key"},
    }
    with patch("trading_onboarding.send_text_with_keyboard", new=AsyncMock()):
        handled = await ob.handle_text(None, 111, "my-binance-secret")

    assert handled is True
    creds = trading_storage.get_api_credentials(111, "binance")
    assert creds["api_key"] == "my-binance-key"
    assert creds["api_secret"] == "my-binance-secret"
    assert ob._onboarding[111]["step"] == "add_bybit_choice"


@pytest.mark.asyncio
async def test_add_bybit_no_finishes_onboarding():
    ob._onboarding[111] = {"step": "add_bybit_choice", "data": {}}
    with patch("trading_onboarding.send_text", new=AsyncMock()) as mock_send:
        handled = await ob.handle_callback(None, 111, "add_bybit:no")

    assert handled is True
    assert 111 not in ob._onboarding  # диалог завершён
    mock_send.assert_called_once()
    assert "готов" in mock_send.call_args[0][2].lower()
    assert trading_storage.get_paper_balance(111) == ob.DEFAULT_PAPER_BALANCE


@pytest.mark.asyncio
async def test_add_bybit_yes_asks_for_bybit_key():
    ob._onboarding[111] = {"step": "add_bybit_choice", "data": {}}
    with patch("trading_onboarding.send_text", new=AsyncMock()):
        handled = await ob.handle_callback(None, 111, "add_bybit:yes")

    assert handled is True
    assert ob._onboarding[111]["step"] == "api_bybit_key"


@pytest.mark.asyncio
async def test_api_bybit_key_step_saves_and_asks_secret():
    ob._onboarding[111] = {"step": "api_bybit_key", "data": {}}
    with patch("trading_onboarding.send_text", new=AsyncMock()):
        handled = await ob.handle_text(None, 111, "my-bybit-key")

    assert handled is True
    assert ob._onboarding[111]["data"]["bybit_api_key"] == "my-bybit-key"
    assert ob._onboarding[111]["step"] == "api_bybit_secret"


@pytest.mark.asyncio
async def test_api_bybit_secret_step_saves_credentials_and_finishes():
    ob._onboarding[111] = {
        "step": "api_bybit_secret",
        "data": {"bybit_api_key": "my-bybit-key"},
    }
    with patch("trading_onboarding.send_text", new=AsyncMock()) as mock_send:
        handled = await ob.handle_text(None, 111, "my-bybit-secret")

    assert handled is True
    creds = trading_storage.get_api_credentials(111, "bybit")
    assert creds["api_key"] == "my-bybit-key"
    assert creds["api_secret"] == "my-bybit-secret"
    assert 111 not in ob._onboarding
    mock_send.assert_called_once()
    assert trading_storage.get_paper_balance(111) == ob.DEFAULT_PAPER_BALANCE


@pytest.mark.asyncio
async def test_full_defaults_flow_end_to_end():
    """Полный путь: старт -> дефолты -> ключ Binance -> секрет -> отказ от Bybit -> готово."""
    with patch("trading_onboarding.send_text_with_keyboard", new=AsyncMock()), \
         patch("trading_onboarding.send_text", new=AsyncMock()):
        await ob.start_trading_setup(None, 555)
        await ob.handle_callback(None, 555, "trading_setup:defaults")
        await ob.handle_text(None, 555, "binance-key")
        await ob.handle_text(None, 555, "binance-secret")
        await ob.handle_callback(None, 555, "add_bybit:no")

    assert trading_storage.has_profile(555) is True
    creds = trading_storage.get_api_credentials(555, "binance")
    assert creds["api_key"] == "binance-key"
    assert 555 not in ob._onboarding
