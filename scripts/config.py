"""Load .env + config.yaml into a single dict."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
import yaml
from dotenv import dotenv_values


class ConfigError(Exception):
    """Raised when config or env is missing/invalid."""


# 所有 key 均为可选：默认免费源（GDELT + RSS）无需任何 key。
# 填了哪个 key、并在 config.yaml 把对应 source 设为 enabled: true，才会启用该付费源。
OPTIONAL_KEYS = ["ALPHA_VANTAGE_KEY", "FINNHUB_KEY", "NEWSAPI_KEY", "CRYPTOPANIC_KEY"]


def load_config(root_dir: Path | None = None) -> dict[str, Any]:
    """Load config from ~/.forex-sentiment/.env (optional) and config.yaml.

    Args:
        root_dir: override the default ~/.forex-sentiment (used for tests).
    """
    root = root_dir or Path.home() / ".forex-sentiment"
    env_path = root / ".env"
    yaml_path = root / "config.yaml"

    # .env 是可选的——没有它也能用免费源跑起来
    env = dotenv_values(env_path) if env_path.exists() else {}

    if not yaml_path.exists():
        raise ConfigError(
            f"config.yaml not found at {yaml_path}. Copy templates/default_config.yaml "
            f"(or run: python -c 'from scripts.config import bootstrap_runtime_dir; bootstrap_runtime_dir()')."
        )

    with open(yaml_path) as f:
        cfg = yaml.safe_load(f)

    cfg["api_keys"] = {
        "alpha_vantage": env.get("ALPHA_VANTAGE_KEY", ""),
        "finnhub": env.get("FINNHUB_KEY", ""),
        "newsapi": env.get("NEWSAPI_KEY", ""),
        "cryptopanic": env.get("CRYPTOPANIC_KEY", ""),
    }
    if env.get("FINNHUB_WEBHOOK_SECRET"):
        cfg["api_keys"]["finnhub_webhook_secret"] = env["FINNHUB_WEBHOOK_SECRET"]

    # Expand ~ in paths
    for key in ("report_dir", "cache_dir"):
        if key in cfg.get("output", {}):
            cfg["output"][key] = str(Path(cfg["output"][key]).expanduser())

    return cfg


def bootstrap_runtime_dir() -> Path:
    """Ensure ~/.forex-sentiment exists; copy default config if not present."""
    root = Path.home() / ".forex-sentiment"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    yaml_path = root / "config.yaml"
    if not yaml_path.exists():
        skill_default = Path(__file__).parent.parent / "templates" / "default_config.yaml"
        if skill_default.exists():
            yaml_path.write_text(skill_default.read_text())
    return root
