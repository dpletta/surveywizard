"""Unit tests for structured conversion reports."""

from __future__ import annotations

import json

from surveywizard.report import Report


class TestReportSerialization:
    def test_json_payload_includes_categories_and_action(self) -> None:
        report = Report(direction="redcap→qualtrics", source_name="Demo")
        report.info(
            "redcap:matrix_group",
            "qsf:Matrix",
            "Grouped fields.",
            "field_1",
            category="matrix_grouping",
        )
        report.warn(
            "redcap:calc",
            "qsf:DB/TB",
            "Needs manual review.",
            "field_2",
            category="lossy_field_mapping",
        )

        payload = json.loads(report.to_json())

        assert payload["recommended_action"] == "review_report"
        assert payload["counts"]["warning"] == 1
        assert payload["categories"][0]["category"] == "lossy_field_mapping"
        assert payload["items"][0]["category"] == "matrix_grouping"

    def test_markdown_renders_category_column(self) -> None:
        report = Report(direction="qualtrics→redcap", source_name="Demo")
        report.error(
            "qsf:flow",
            "redcap:events",
            "Dropped unsupported flow node.",
            "SV_123",
            category="flow_node_ignored",
        )

        markdown = report.to_markdown()

        assert "| Level | Category | Field | From → To | Detail |" in markdown
        assert "`flow node ignored`" in markdown
