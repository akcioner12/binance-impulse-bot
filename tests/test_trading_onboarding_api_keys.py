import pytest
from unittest.mock import AsyncMock, patch

import trading_onboarding as ob
import trading_storage


def setup_function():
    trading_storage.init_trading_db()
    trading_storage.init_paper_trading_db()
    ob._onboarding.clear()


@pytest.mark.asyncio
async def test_exchange_choice_binance_asks_for_key():
    ob._onboarding[111] = {"step": "exchange_choice", "data": {}}
    with patch("trading_onboarding.send_text", new=AsyncMock()) as mock_send:
        handled = await ob.handle_callback(None, 111, "exchange_choice:binance")

    assert handled is True
    assert ob._onboarding[111]["step"] == "api_key"
    assert ob._onboarding[111]["data"]["current_exchange"] == "binance"
    assert ob._onboarding[111]["data"]["is_second_exchange"] is False
    assert "binance" in mock_send.call_args[0][2].lower()


@pytest.mark.asyncio
async def test_exchange_choice_bybit_asks_for_key():
    ob._onboarding[111] = {"step": "exchange_choice", "data": {}}
    with patch("trading_onboarding.send_text", new=AsyncMock()) as mock_send:
        handled = await ob.handle_callback(None, 111, "exchange_choice:bybit")

    assert handled is True
    assert ob._onboarding[111]["step"] == "api_key"
    assert ob._onboarding[111]["data"]["current_exchange"] == "bybit"
    assert "bybit" in mock_send.call_args[0][2].lower()


@pytest.mark.asyncio
async def test_api_key_step_saves_and_asks_secret():
    ob._onboarding[111] = {"step": "api_key", "data": {"current_exchange": "bybit"}}
    with patch("trading_onboarding.send_text", new=AsyncMock()):
        handled = await ob.handle_text(None, 111, "my-bybit-key")

    assert handled is True
    assert ob._onboarding[111]["data"]["api_key"] == "my-bybit-key"
    assert ob._onboarding[111]["step"] == "api_secret"


@pytest.mark.asyncio
async def test_api_secret_first_exchange_saves_and_offers_other():
    ob._onboarding[111] = {
        "step": "api_secret",
        "data": {"current_exchange": "binance", "api_key": "my-key", "is_second_exchange": False},
    }
    with patch("trading_onboarding.send_text_with_keyboard", new=AsyncMock()):
        handled = await ob.handle_text(None, 111, "my-secret")

    assert handled is True
    creds = trading_storage.get_api_credentials(111, "binance")
    assert creds["api_key"] == "my-key"
    assert creds["api_secret"] == "my-secret"
    assert ob._onboarding[111]["step"] == "add_other_exchange_choice"
    assert ob._onboarding[111]["data"]["other_exchange"] == "bybit"
    # Онбординг ещё не завершён -- paper-баланс пока не создан
    assert trading_storage.get_paper_balance(111) is None


@pytest.mark.asyncio
async def test_api_secret_first_exchange_bybit_offers_binance():
    """Если первой выбрана Bybit (нет доступа к Binance в РФ), второй предлагается Binance."""
    ob._onboarding[111] = {
        "step": "api_secret",
        "data": {"current_exchange": "bybit", "api_key": "my-key", "is_second_exchange": False},
    }
    with patch("trading_onboarding.send_text_with_keyboard", new=AsyncMock()):
        await ob.handle_text(None, 111, "my-secret")

    assert ob._onboarding[111]["data"]["other_exchange"] == "binance"


@pytest.mark.asyncio
async def test_add_other_exchange_no_finishes_onboarding():
    ob._onboarding[111] = {
        "step": "add_other_exchange_choice",
        "data": {"current_exchange": "binance", "other_exchange": "bybit"},
    }
    with patch("trading_onboarding.send_text", new=AsyncMock()) as mock_send:
        handled = await ob.handle_callback(None, 111, "add_other_exchange:no")

    assert handled is True
    assert 111 not in ob._onboarding
    mock_send.assert_called_once()
    assert "готов" in mock_send.call_args[0][2].lower()
    assert trading_storage.get_paper_balance(111) == ob.DEFAULT_PAPER_BALANCE


@pytest.mark.asyncio
async def test_add_other_exchange_yes_asks_for_other_key():
    ob._onboarding[111] = {
        "step": "add_other_exchange_choice",
        "data": {"current_exchange": "binance", "other_exchange": "bybit"},
    }
    with patch("trading_onboarding.send_text", new=AsyncMock()):
        handled = await ob.handle_callback(None, 111, "add_other_exchange:yes")

    assert handled is True
    assert ob._onboarding[111]["step"] == "api_key"
    assert ob._onboarding[111]["data"]["current_exchange"] == "bybit"
    assert ob._onboarding[111]["data"]["is_second_exchange"] is True


@pytest.mark.asyncio
async def test_api_secret_second_exchange_finishes_onboarding():
    ob._onboarding[111] = {
        "step": "api_secret",
        "data": {"current_exchange": "bybit", "api_key": "my-bybit-key", "is_second_exchange": True},
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
async def test_full_defaults_flow_binance_only_end_to_end():
    """Полный путь: старт -> дефолты -> выбор Binance -> ключ -> секрет -> пропустить вторую биржу -> готово."""
    with patch("trading_onboarding.send_text_with_keyboard", new=AsyncMock()), \
         patch("trading_onboarding.send_text", new=AsyncMock()):
        await ob.start_trading_setup(None, 555)
        await ob.handle_callback(None, 555, "trading_setup:defaults")
        await ob.handle_callback(None, 555, "exchange_choice:binance")
        await ob.handle_text(None, 555, "binance-key")
        await ob.handle_text(None, 555, "binance-secret")
        await ob.handle_callback(None, 555, "add_other_exchange:no")

    assert trading_storage.has_profile(555) is True
    creds = trading_storage.get_api_credentials(555, "binance")
    assert creds["api_key"] == "binance-key"
    assert trading_storage.get_api_credentials(555, "bybit") is None
    assert 555 not in ob._onboarding


@pytest.mark.asyncio
async def test_full_defaults_flow_bybit_only_end_to_end():
    """Пользователь без доступа к Binance выбирает сразу Bybit и пропускает Binance."""
    with patch("trading_onboarding.send_text_with_keyboard", new=AsyncMock()), \
         patch("trading_onboarding.send_text", new=AsyncMock()):
        await ob.start_trading_setup(None, 777)
        await ob.handle_callback(None, 777, "trading_setup:defaults")
        await ob.handle_callback(None, 777, "exchange_choice:bybit")
        await ob.handle_text(None, 777, "bybit-key")
        await ob.handle_text(None, 777, "bybit-secret")
        await ob.handle_callback(None, 777, "add_other_exchange:no")

    assert trading_storage.has_profile(777) is True
    creds = trading_storage.get_api_credentials(777, "bybit")
    assert creds["api_key"] == "bybit-key"
    assert trading_storage.get_api_credentials(777, "binance") is None
    assert 777 not in ob._onboarding


@pytest.mark.asyncio
async def test_full_defaults_flow_both_exchanges_end_to_end():
    """Пользователь настраивает обе биржи: сначала Bybit, потом соглашается добавить Binance."""
    with patch("trading_onboarding.send_text_with_keyboard", new=AsyncMock()), \
         patch("trading_onboarding.send_text", new=AsyncMock()):
        await ob.start_trading_setup(None, 999)
        await ob.handle_callback(None, 999, "trading_setup:defaults")
        await ob.handle_callback(None, 999, "exchange_choice:bybit")
        await ob.handle_text(None, 999, "bybit-key")
        await ob.handle_text(None, 999, "bybit-secret")
        await ob.handle_callback(None, 999, "add_other_exchange:yes")
        await ob.handle_text(None, 999, "binance-key")
        await ob.handle_text(None, 999, "binance-secret")

    bybit_creds = trading_storage.get_api_credentials(999, "bybit")
    binance_creds = trading_storage.get_api_credentials(999, "binance")
    assert bybit_creds["api_key"] == "bybit-key"
    assert binance_creds["api_key"] == "binance-key"
    assert 999 not in ob._onboarding
    assert trading_storage.get_paper_balance(999) == ob.DEFAULT_PAPER_BALANCE
