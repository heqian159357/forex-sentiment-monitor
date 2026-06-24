import pytest
from pathlib import Path

@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent / "fixtures"

@pytest.fixture
def sample_config():
    return {
        "default_symbols": ["BTC", "ETH", "XAUUSD", "EURUSD"],
        "symbol_keywords": {
            "BTC": ["bitcoin", "btc"],
            "ETH": ["ethereum", "eth"],
            "XAUUSD": ["gold", "xau"],
            "EURUSD": ["euro", "eur/usd", "欧元"],
        },
        "default_window_hours": 24,
        "max_candidates_for_review": 20,
        "score_weights": {"claude": 0.6, "api_only": 0.4},
        "alert_thresholds": {"extreme_bearish": -0.5, "extreme_bullish": 0.5},
    }
