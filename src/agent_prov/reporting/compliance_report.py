"""Compliance Report Generator.

Reads a sealed Pipeline Bundle (JSON) and produces a PDF that maps every
record - and the bundle itself - to the EU AI Act clauses each field
substantiates. Two artifacts in one document: a per-record audit trail and
an aggregate clause-coverage matrix.
"""

from __future__ import annotations

import pathlib
from typing import Any

from agent_prov.reporting._pdf import (
    _ReportPDF,
    _bundle_metadata_rows,
    _coverage_rows,
    _record_clause_rows,
    _record_field_rows,
    _record_summary_rows,
)
from agent_prov.reporting.obligations import CLAUSE_DESCRIPTION, OBLIGATION_MAP, _field_present


class ComplianceReport:
    """Builds compliance artifacts from a sealed Pipeline Bundle."""

    def __init__(self, bundle: dict[str, Any]) -> None:
        if not isinstance(bundle, dict):
            raise TypeError("bundle must be a dict")
        if bundle.get("record_type") != "pipeline_bundle":
            raise ValueError(
                "bundle.record_type must be 'pipeline_bundle' "
                f"(got {bundle.get('record_type')!r})"
            )
        if "records" not in bundle:
            raise ValueError("bundle is missing the 'records' list")
        self.bundle = bundle

    def coverage(self) -> dict[str, list[str]]:
        """Map each Act clause to the ids (bundle_id or record_id) that satisfy it.

        A clause is satisfied by a record/bundle when the entity carries at
        least one populated field mapped to that clause.
        """
        result: dict[str, list[str]] = {clause: [] for clause in CLAUSE_DESCRIPTION}

        bundle_id = self.bundle["bundle_id"]
        for field, clauses in OBLIGATION_MAP["pipeline_bundle"].items():
            if _field_present(self.bundle, field):
                for clause in clauses:
                    if bundle_id not in result[clause]:
                        result[clause].append(bundle_id)

        for record in self.bundle["records"]:
            mapping = OBLIGATION_MAP.get(record.get("record_type"), {})
            rid = record.get("record_id")
            for field, clauses in mapping.items():
                if _field_present(record, field):
                    for clause in clauses:
                        if rid not in result[clause]:
                            result[clause].append(rid)
        return result

    def to_pdf(self, path: str | pathlib.Path) -> pathlib.Path:
        """Render the compliance report to *path* and return the absolute path."""
        pdf = _ReportPDF(self.bundle["bundle_id"])
        pdf.set_auto_page_break(auto=True, margin=18)
        pdf.add_page()

        pdf.render_title("EU AI Act Compliance Report")
        pdf.render_subtitle(
            f"Pipeline Bundle {self.bundle['bundle_id']}  |  "
            f"protocol v{self.bundle.get('protocol_version', '?')}"
        )

        pdf.section_heading("Bundle metadata")
        pdf.kv_table(_bundle_metadata_rows(self.bundle))

        pdf.section_heading("Record summary")
        pdf.kv_table(_record_summary_rows(self.bundle))

        for index, record in enumerate(self.bundle["records"], start=1):
            pdf.section_heading(
                f"Record {index} - {record['record_type']}"
            )
            pdf.kv_table(_record_field_rows(record))
            clause_rows = _record_clause_rows(record)
            if clause_rows:
                pdf.subsection("Mapped EU AI Act clauses")
                pdf.two_col_table(("Clause", "Obligation"), clause_rows)

        pdf.section_heading("Clause coverage matrix")
        pdf.three_col_table(
            ("Clause", "Obligation", "Satisfied by"),
            _coverage_rows(self.coverage()),
        )

        out_path = pathlib.Path(path)
        pdf.output(str(out_path))
        return out_path.resolve()
