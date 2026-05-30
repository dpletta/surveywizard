"""Conversion report — collects and renders per-field degradations.

A ``Report`` accumulates ``Degradation`` records describing cases where a
field's meaning couldn't be preserved perfectly across formats (e.g. REDCap
``calc`` has no Qualtrics equivalent, Qualtrics ``WebService`` flow has no
REDCap equivalent). Rendered as a sidecar Markdown file next to the output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class Level(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Degradation:
    level: Level
    field_oid: str | None
    from_type: str
    to_type: str
    detail: str
    category: str = "general"

    def to_payload(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "category": self.category,
            "field": self.field_oid,
            "from_type": self.from_type,
            "to_type": self.to_type,
            "detail": self.detail,
        }


@dataclass
class Report:
    direction: str  # "redcap→qualtrics" or "qualtrics→redcap"
    source_name: str = ""
    items: list[Degradation] = field(default_factory=list)

    def add(
        self,
        level: Level,
        from_type: str,
        to_type: str,
        detail: str,
        field_oid: str | None = None,
        *,
        category: str = "general",
    ) -> None:
        self.items.append(
            Degradation(
                level=level,
                field_oid=field_oid,
                from_type=from_type,
                to_type=to_type,
                detail=detail,
                category=category,
            )
        )

    def info(
        self,
        from_type: str,
        to_type: str,
        detail: str,
        field_oid: str | None = None,
        *,
        category: str = "general",
    ) -> None:
        self.add(Level.INFO, from_type, to_type, detail, field_oid, category=category)

    def warn(
        self,
        from_type: str,
        to_type: str,
        detail: str,
        field_oid: str | None = None,
        *,
        category: str = "general",
    ) -> None:
        self.add(Level.WARNING, from_type, to_type, detail, field_oid, category=category)

    def error(
        self,
        from_type: str,
        to_type: str,
        detail: str,
        field_oid: str | None = None,
        *,
        category: str = "general",
    ) -> None:
        self.add(Level.ERROR, from_type, to_type, detail, field_oid, category=category)

    def has_problems(self) -> bool:
        """True if any warning- or error-level items were recorded."""
        return any(i.level in (Level.WARNING, Level.ERROR) for i in self.items)

    def counts(self) -> dict[Level, int]:
        out: dict[Level, int] = {Level.INFO: 0, Level.WARNING: 0, Level.ERROR: 0}
        for item in self.items:
            out[item.level] += 1
        return out

    def category_breakdown(self) -> list[dict[str, Any]]:
        categories: dict[str, dict[str, Any]] = {}
        for item in self.items:
            bucket = categories.setdefault(
                item.category,
                {
                    "category": item.category,
                    "count": 0,
                    "levels": {
                        Level.INFO.value: 0,
                        Level.WARNING.value: 0,
                        Level.ERROR.value: 0,
                    },
                    "fields": [],
                },
            )
            bucket["count"] += 1
            bucket["levels"][item.level.value] += 1
            if (
                item.field_oid
                and item.field_oid not in bucket["fields"]
                and len(bucket["fields"]) < 5
            ):
                bucket["fields"].append(item.field_oid)
        return sorted(
            categories.values(),
            key=lambda bucket: (
                -bucket["levels"][Level.ERROR.value],
                -bucket["levels"][Level.WARNING.value],
                -bucket["count"],
                bucket["category"],
            ),
        )

    def problem_items(self) -> list[Degradation]:
        return [item for item in self.items if item.level in {Level.WARNING, Level.ERROR}]

    def to_payload(self) -> dict[str, Any]:
        generated = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%SZ")
        counts = self.counts()
        if counts[Level.ERROR]:
            recommended_action = "manual_cleanup_needed"
        elif counts[Level.WARNING]:
            recommended_action = "review_report"
        else:
            recommended_action = "safe"
        return {
            "direction": self.direction,
            "source_name": self.source_name,
            "generated_at": generated,
            "counts": {
                Level.INFO.value: counts[Level.INFO],
                Level.WARNING.value: counts[Level.WARNING],
                Level.ERROR.value: counts[Level.ERROR],
            },
            "recommended_action": recommended_action,
            "categories": self.category_breakdown(),
            "items": [item.to_payload() for item in self.items],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), indent=2, ensure_ascii=False)

    # ----- rendering

    def to_markdown(self) -> str:
        counts = self.counts()
        generated = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%SZ")
        lines = [
            f"# SurveyWizard Conversion Report — {self.direction}",
            "",
            f"- **Source:** `{self.source_name}`" if self.source_name else "",
            f"- **Generated:** {generated}",
            f"- **Totals:** {counts[Level.INFO]} info, "
            f"{counts[Level.WARNING]} warnings, {counts[Level.ERROR]} errors",
            "",
        ]
        lines = [line for line in lines if line != ""] + [""]

        if not self.items:
            lines.append("_No degradations reported — the conversion is expected to be lossless._")
            return "\n".join(lines) + "\n"

        lines.append("## Details")
        lines.append("")
        lines.append("| Level | Category | Field | From → To | Detail |")
        lines.append("|-------|----------|-------|-----------|--------|")
        for item in self.items:
            field_cell = f"`{item.field_oid}`" if item.field_oid else "—"
            level_cell = item.level.value.upper()
            transition = f"`{item.from_type}` → `{item.to_type}`"
            detail = item.detail.replace("\n", " ").replace("|", "\\|")
            category_cell = item.category.replace("_", " ")
            lines.append(
                f"| {level_cell} | `{category_cell}` | {field_cell} | {transition} | {detail} |"
            )

        lines.extend(
            [
                "",
                "## Legend",
                "",
                "- **INFO**: expected semantic match, noted for traceability.",
                "- **WARNING**: the target format approximates the source — review before trusting.",
                "- **ERROR**: the field cannot be represented; the importer may drop or misread it.",
                "",
            ]
        )
        return "\n".join(lines)

    def write(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(self.to_markdown())

    def write_json(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(self.to_json())


__all__ = ["Degradation", "Level", "Report"]
