"""Alert notification hook. v1: log only. v2 (agent): fill in push channels."""
from __future__ import annotations
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def notify(alerts: list[dict], report_paths: dict, config: dict) -> None:
    if not alerts:
        log.info("No alerts to notify.")
        return
    for a in alerts:
        log.warning(f"[ALERT] {a['rule']} symbol={a.get('symbol')} — {a.get('message')}")
