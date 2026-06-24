"""敏感词过滤：硬禁用 + 软改写。

应用于 reviewed.json 中的自然语言字段（industry_reason / analysis_detail /
divergence_note）。在 render_report.py 渲染前调用。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

TEXT_FIELDS = ("industry_reason", "analysis_detail", "divergence_note")


@dataclass
class FilterStats:
    blocked: list[dict] = field(default_factory=list)
    rewrites: list[dict] = field(default_factory=list)

    @property
    def has_block(self) -> bool:
        return bool(self.blocked)


class HardBlockError(ValueError):
    """硬禁用命中。携带完整 stats 供审计落盘。"""

    def __init__(self, message: str, stats: FilterStats):
        super().__init__(message)
        self.stats = stats


def load_word_lists(yaml_path: Path | None = None) -> tuple[list[str], dict[str, str]]:
    if yaml_path is None:
        yaml_path = Path(__file__).parent / "prompts" / "sensitive_words.yaml"
    with open(yaml_path) as f:
        data = yaml.safe_load(f) or {}
    hard = list(data.get("hard_block") or [])
    soft = dict(data.get("soft_rewrite") or {})
    return hard, soft


def scan_and_rewrite(
    reviews: list[dict],
    hard_block: list[str],
    soft_rewrite: dict[str, str],
) -> FilterStats:
    """对 reviews in-place 应用敏感词过滤。

    - 硬禁用：记录到 stats.blocked，不修改文本（由调用方决定如何处理）
    - 软改写：直接替换文本，记录到 stats.rewrites
    """
    stats = FilterStats()
    for r in reviews:
        for field_name in TEXT_FIELDS:
            text = r.get(field_name) or ""
            if not text:
                continue

            for word in hard_block:
                if word in text:
                    stats.blocked.append({
                        "review_id": r.get("id"),
                        "field": field_name,
                        "word": word,
                        "snippet": text,
                    })

            new_text = text
            for src, dst in soft_rewrite.items():
                if src in new_text:
                    stats.rewrites.append({
                        "review_id": r.get("id"),
                        "field": field_name,
                        "from": src,
                        "to": dst,
                    })
                    new_text = new_text.replace(src, dst)
            if new_text != text:
                r[field_name] = new_text
    return stats


def apply_filter(
    reviewed_data: dict[str, Any],
    yaml_path: Path | None = None,
    *,
    strict: bool = True,
) -> FilterStats:
    """对 reviewed.json 数据做过滤。

    Args:
        reviewed_data: load 后的 reviewed.json dict
        strict: True 时，命中硬禁用 → 抛 ValueError；False 仅记录
    """
    hard, soft = load_word_lists(yaml_path)
    stats = scan_and_rewrite(reviewed_data.get("reviews", []), hard, soft)

    if stats.rewrites:
        log.info(
            "敏感词软改写命中 %d 处：%s",
            len(stats.rewrites),
            ", ".join(f"{r['from']}→{r['to']}" for r in stats.rewrites[:5]),
        )
    if stats.blocked:
        log.warning(
            "敏感词硬禁用命中 %d 处（review_id: %s）",
            len(stats.blocked),
            ", ".join(b["review_id"][:8] for b in stats.blocked[:5]),
        )
        if strict:
            words = ", ".join(sorted({b["word"] for b in stats.blocked}))
            raise HardBlockError(
                f"敏感词命中硬禁用：{words}。请重新生成 reviewed.json 或人工修订后再渲染。",
                stats,
            )

    return stats
