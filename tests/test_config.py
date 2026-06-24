import os
import tempfile
from pathlib import Path
from scripts.config import load_config, ConfigError


def test_load_config_merges_env_and_yaml():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".env").write_text("ALPHA_VANTAGE_KEY=av-k\nFINNHUB_KEY=f-k\nNEWSAPI_KEY=n-k\n")
        (root / "config.yaml").write_text(
            "default_symbols: [BTC]\n"
            "default_window_hours: 12\n"
            "max_candidates_for_review: 10\n"
            "score_weights: {claude: 0.6, api_only: 0.4}\n"
            "alert_thresholds: {extreme_bearish: -0.5, extreme_bullish: 0.5}\n"
            "sources:\n"
            "  alpha_vantage: {enabled: true, timeout_seconds: 15, retry: 2, rate_limit_per_minute: 5, daily_quota: 25}\n"
            "  finnhub: {enabled: true, timeout_seconds: 10, retry: 2, rate_limit_per_minute: 60}\n"
            "  newsapi: {enabled: true, timeout_seconds: 10, retry: 2, daily_quota: 100}\n"
            "output: {report_dir: ~/reports, cache_dir: ~/cache, keep_cache_days: 30}\n"
            "symbol_keywords: {BTC: [bitcoin]}\n"
        )
        cfg = load_config(root_dir=root)
        assert cfg["api_keys"]["alpha_vantage"] == "av-k"
        assert cfg["default_symbols"] == ["BTC"]
        assert cfg["default_window_hours"] == 12


def test_load_config_without_env_works():
    """开源版：无 .env 也能加载（默认免费源无需 key），key 为空字符串。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "config.yaml").write_text("default_symbols: [BTC]\n")
        cfg = load_config(root_dir=root)
        assert cfg["api_keys"]["alpha_vantage"] == ""
        assert cfg["api_keys"]["finnhub"] == ""
        assert cfg["default_symbols"] == ["BTC"]


def test_load_config_missing_yaml_raises():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".env").write_text("ALPHA_VANTAGE_KEY=av-k\n")
        try:
            load_config(root_dir=root)
        except ConfigError as e:
            assert "config.yaml" in str(e)
            return
        raise AssertionError("expected ConfigError")


def test_load_config_partial_keys_ok():
    """只填一个 key 也不报错，其余为空字符串（对应源会被跳过）。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".env").write_text("ALPHA_VANTAGE_KEY=av-k\n")
        (root / "config.yaml").write_text("default_symbols: [BTC]\n")
        cfg = load_config(root_dir=root)
        assert cfg["api_keys"]["alpha_vantage"] == "av-k"
        assert cfg["api_keys"]["finnhub"] == ""
        assert cfg["api_keys"]["newsapi"] == ""
