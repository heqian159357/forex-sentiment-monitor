"""审计日志落盘 (~/.forex-sentiment/audit.log)。

用途：合规追溯每一次 run 的完整决策链路：
- 谁触发的（actor + ts + run_id）
- 用的什么配置/模型/prompt（config_hash + model_id + prompt_versions）
- 输入/输出文件指纹（防事后篡改）
- 内容过滤明细（每条软改写 from/to + 硬禁用拦截）
- 告警 / 重试 / 退出码

格式：JSON Lines (jsonl)，append-only，文件权限 400。
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import socket
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIT_PATH_DEFAULT = Path.home() / ".forex-sentiment" / "audit.log"


def _sha256_file(p: Path) -> str | None:
    if not p.exists():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _sha256_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def hash_config(config: dict[str, Any]) -> str:
    """对 config dict 做规范化哈希（排除 api_keys 防泄露）。"""
    safe = {k: v for k, v in config.items() if k != "api_keys"}
    canonical = json.dumps(safe, sort_keys=True, ensure_ascii=False)
    return _sha256_text(canonical)


def hash_prompt_files(prompt_dir: Path) -> dict[str, str]:
    """对 prompts/ 目录下每个 .md / .yaml 文件计算哈希。"""
    out: dict[str, str] = {}
    for f in sorted(prompt_dir.glob("*")):
        if f.suffix in (".md", ".yaml", ".yml") and f.is_file():
            h = _sha256_file(f)
            if h:
                out[f.stem] = h
    return out


@dataclass
class AuditRecord:
    """单次 run 的审计记录。所有字段均必填，缺失值用空 dict/list/None。"""

    ts: str
    run_id: str
    actor: str
    host: str
    skill_version: str
    config_hash: str
    model_id: str
    prompt_versions: dict[str, str]
    inputs: dict[str, str | None]      # raw_news / candidates / reviewed → 文件 sha256
    outputs: dict[str, str | None]     # report_md / report_html / alerts → 文件 sha256
    tier: str
    filter_summary: dict[str, int]     # hard_blocks_count / soft_rewrites_count
    filter_details: dict[str, list]    # hard_blocks: [...], soft_rewrites: [...]
    alerts: list[dict]
    retries: dict[str, int]            # 各阶段重试次数
    exit_code: int
    duration_ms: int
    notes: str = ""


def make_record(
    *,
    run_id: str | None = None,
    actor: str | None = None,
    skill_version: str = "1.0.0",
    config: dict[str, Any] | None = None,
    model_id: str = "claude-opus-4-7",
    prompt_dir: Path | None = None,
    raw_path: Path | None = None,
    candidates_path: Path | None = None,
    reviewed_path: Path | None = None,
    report_md_path: Path | None = None,
    report_html_path: Path | None = None,
    alerts_path: Path | None = None,
    tier: str = "A",
    filter_stats: Any = None,           # FilterStats 实例（dataclass）
    alerts: list[dict] | None = None,
    retries: dict[str, int] | None = None,
    exit_code: int = 0,
    duration_ms: int = 0,
    notes: str = "",
) -> AuditRecord:
    return AuditRecord(
        ts=datetime.now(timezone.utc).isoformat(),
        run_id=run_id or str(uuid.uuid4()),
        actor=actor or f"{getpass.getuser()}@{socket.gethostname()}",
        host=socket.gethostname(),
        skill_version=skill_version,
        config_hash=hash_config(config or {}),
        model_id=model_id,
        prompt_versions=hash_prompt_files(prompt_dir) if prompt_dir else {},
        inputs={
            "raw_news": _sha256_file(raw_path) if raw_path else None,
            "candidates": _sha256_file(candidates_path) if candidates_path else None,
            "reviewed": _sha256_file(reviewed_path) if reviewed_path else None,
        },
        outputs={
            "report_md": _sha256_file(report_md_path) if report_md_path else None,
            "report_html": _sha256_file(report_html_path) if report_html_path else None,
            "alerts": _sha256_file(alerts_path) if alerts_path else None,
        },
        tier=tier,
        filter_summary={
            "hard_blocks_count": len(filter_stats.blocked) if filter_stats else 0,
            "soft_rewrites_count": len(filter_stats.rewrites) if filter_stats else 0,
        },
        filter_details={
            "hard_blocks": list(filter_stats.blocked) if filter_stats else [],
            "soft_rewrites": list(filter_stats.rewrites) if filter_stats else [],
        },
        alerts=list(alerts or []),
        retries=dict(retries or {}),
        exit_code=exit_code,
        duration_ms=duration_ms,
        notes=notes,
    )


def write_record(record: AuditRecord, path: Path | None = None) -> Path:
    """append 一条记录，确保文件权限 600（目录 700）。"""
    target = path or AUDIT_PATH_DEFAULT
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    line = json.dumps(asdict(record), ensure_ascii=False)
    with open(target, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    try:
        os.chmod(target, 0o600)
    except PermissionError:
        pass
    return target
