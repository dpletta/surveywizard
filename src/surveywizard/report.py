"""Conversion report — collects and renders per-field degradations.

A ``Report`` accumulates ``Degradation`` records describing cases where a
field's meaning couldn't be preserved perfectly across formats (e.g. REDCap
``calc`` has no Qualtrics equivalent, Qualtrics ``WebService`` flow has no
REDCap equivalent). Rendered as a sidecar Markdown file next to the output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


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
    ) -> None:
        self.items.append(
            Degradation(level=level, field_oid=field_oid, from_type=from_type,
                        to_type=to_type, detail=detail)
        )

    def info(self, from_type: str, to_type: str, detail: str, field_oid: str | None = None) -> None:
        self.add(Level.INFO, from_type, to_type, detail, field_oid)

    def warn(self, from_type: str, to_type: str, detail: str, field_oid: str | None = None) -> None:
        self.add(Level.WARNING, from_type, to_type, detail, field_oid)

    def error(
        self, from_type: str, to_type: str, detail: str, field_oid: str | None = None
    ) -> None:
        self.add(Level.ERROR, from_type, to_type, detail, field_oid)

    def has_problems(self) -> bool:
        """True if any warning- or error-level items were recorded."""
        return any(i.level in (Level.WARNING, Level.ERROR) for i in self.items)

    def counts(self) -> dict[Level, int]:
        out: dict[Level, int] = {Level.INFO: 0, Level.WARNING: 0, Level.ERROR: 0}
        for item in self.items:
            out[item.level] += 1
        return out

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
        lines.append("| Level | Field | From → To | Detail |")
        lines.append("|-------|-------|-----------|--------|")
        for item in self.items:
            field_cell = f"`{item.field_oid}`" if item.field_oid else "—"
            level_cell = item.level.value.upper()
            transition = f"`{item.from_type}` → `{item.to_type}`"
            detail = item.detail.replace("\n", " ").replace("|", "\\|")
            lines.append(f"| {level_cell} | {field_cell} | {transition} | {detail} |")

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


__all__ = ["Degradation", "Level", "Report"]
