import pytest
from opspilot.config import Settings

def test_settings_defaults():
    settings = Settings()
    assert settings.API_HOST == "0.0.0.0"
    assert settings.API_PORT == 8080
    assert settings.READ_ONLY_MODE is True
    assert settings.MAX_DEEPDIVE_ROUNDS == 3
    assert settings.APP_NAME == "OpsPilot AI"

def test_settings_override():
    settings = Settings(API_PORT=9090, API_HOST="127.0.0.1")
    assert settings.API_PORT == 9090
    assert settings.API_HOST == "127.0.0.1"
