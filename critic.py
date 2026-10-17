
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

VALID_REGIONS = [
    "Sousse", "Tunis", "Djerba", "Monastir", "Nabeul",
    "Hammamet", "Bizerte", "Sfax", "Gabès", "Tozeur"
]


# ============================================================
# VERDICT
# ============================================================

@dataclass
class Verdict:
    passed: bool
    reason: str

    @staticmethod
    def PASS(reason: str = "OK") -> "Verdict":
        return Verdict(passed=True, reason=reason)

    @staticmethod
    def FAIL(reason: str) -> "Verdict":
        return Verdict(passed=False, reason=reason)


# ============================================================
# CRITIC CLASS
# ============================================================

class Critic:

    # ─────────────────────────────────────────────
    # STEP-LEVEL EVALUATION  (Scenario 1 + Scenario 2)
    # ─────────────────────────────────────────────

    def evaluate_step(self, tool_name: str, output: dict, state) -> dict:

        logger.info(f"[Critic] Evaluating step: {tool_name}")

        try:
            # Scenario 1 tools
            if tool_name == "validate_schema":
                verdict = self._check_validate_schema(output)
            elif tool_name == "read_csv":
                verdict = self._check_read_csv(output)
            elif tool_name == "compute_kpi":
                verdict = self._check_compute_kpi(output)
            elif tool_name == "format_output":
                verdict = self._check_format_output(output)
            # Scenario 2 tools
            elif tool_name == "fetch_indicator":
                verdict = self._check_fetch_indicator(output)
            elif tool_name == "validate_api_response":
                verdict = self._check_validate_api_response(output)
            elif tool_name == "transform_to_chart":
                verdict = self._check_transform_to_chart(output)
            else:
                verdict = Verdict.FAIL(
                    f"Unknown tool '{tool_name}' — cannot validate"
                )
        except Exception as e:
            verdict = Verdict.FAIL(f"Critic crashed during evaluation: {e}")

        if verdict.passed:
            logger.info(f"[Critic] PASS — {tool_name}: {verdict.reason}")
        else:
            logger.warning(f"[Critic] FAIL — {tool_name}: {verdict.reason}")

        return {"passed": verdict.passed, "reason": verdict.reason}

    # ─────────────────────────────────────────────
    # SCENARIO 1 — PER-TOOL CHECKS
    # ─────────────────────────────────────────────

    def _check_validate_schema(self, output: dict) -> Verdict:
        if not output.get("schema_valid"):
            return Verdict.FAIL("Schema validation returned False")
        if "columns_found" not in output:
            return Verdict.FAIL("Missing 'columns_found' in schema validation output")
        return Verdict.PASS("Schema is valid")

    def _check_read_csv(self, output: dict) -> Verdict:
        if "records" not in output:
            return Verdict.FAIL("Missing 'records' in read_csv output")
        if not isinstance(output["records"], list):
            return Verdict.FAIL("'records' must be a list")
        if len(output["records"]) == 0:
            return Verdict.FAIL("CSV loaded but contains zero records")
        if "row_count" not in output:
            return Verdict.FAIL("Missing 'row_count' in read_csv output")

        required = ["region", "hotel_name", "month", "occupancy_rate", "revenue_tnd"]
        for i, r in enumerate(output["records"]):
            for field in required:
                if field not in r:
                    return Verdict.FAIL(f"Record {i} missing field '{field}'")

        return Verdict.PASS(f"Loaded {output['row_count']} valid records")

    def _check_compute_kpi(self, output: dict) -> Verdict:
        if "kpis" not in output:
            return Verdict.FAIL("Missing 'kpis' in compute_kpi output")

        kpis = output["kpis"]
        required_fields = [
            "average_occupancy", "total_revenue_tnd",
            "best_region", "anomalies"
        ]
        for field in required_fields:
            if field not in kpis:
                return Verdict.FAIL(f"KPI missing required field: '{field}'")

        occ = kpis["average_occupancy"]
        if not (0 <= occ <= 100):
            return Verdict.FAIL(f"average_occupancy out of range [0,100]: {occ}")

        rev = kpis["total_revenue_tnd"]
        if rev < 0:
            return Verdict.FAIL(f"total_revenue_tnd is negative: {rev}")

        if not isinstance(kpis["anomalies"], list):
            return Verdict.FAIL("'anomalies' must be a list")

        for i, a in enumerate(kpis["anomalies"]):
            if "hotel" not in a or "occupancy" not in a:
                return Verdict.FAIL(
                    f"Anomaly {i} missing 'hotel' or 'occupancy'"
                )
            if a["occupancy"] >= 50:
                return Verdict.FAIL(
                    f"Anomaly {i} has occupancy {a['occupancy']} "
                    f"which is >= 50 — not an anomaly"
                )

        return Verdict.PASS(
            f"KPIs valid: avg_occ={occ}%, revenue={rev} TND, "
            f"best={kpis['best_region']}, anomalies={len(kpis['anomalies'])}"
        )

    def _check_format_output(self, output: dict) -> Verdict:
        if "report" not in output:
            return Verdict.FAIL("Missing 'report' in format_output output")

        report = output["report"]
        required = [
            "average_occupancy", "total_revenue_tnd",
            "best_region", "anomalies"
        ]
        for field in required:
            if field not in report:
                return Verdict.FAIL(f"Report missing field: '{field}'")

        return Verdict.PASS("Report is complete and well-formed")

    # ─────────────────────────────────────────────
    # SCENARIO 2 — PER-TOOL CHECKS
    # ─────────────────────────────────────────────

    def _check_fetch_indicator(self, output: dict) -> Verdict:
        if "raw_response" not in output:
            return Verdict.FAIL("Missing 'raw_response' in fetch_indicator output")
        raw = output["raw_response"]
        if not isinstance(raw, list) or len(raw) != 2:
            return Verdict.FAIL(
                "raw_response must be [metadata, data_array]"
            )
        if output.get("http_status") not in (None, 200):
            return Verdict.FAIL(f"Bad HTTP status: {output.get('http_status')}")
        return Verdict.PASS(
            f"Fetched indicator '{output.get('indicator_key')}' "
            f"(from_cache={output.get('from_cache', False)})"
        )

    def _check_validate_api_response(self, output: dict) -> Verdict:
        if "records" not in output:
            return Verdict.FAIL("Missing 'records' in validate_api_response output")
        if not isinstance(output["records"], list):
            return Verdict.FAIL("'records' must be a list")
        if len(output["records"]) == 0:
            return Verdict.FAIL("Zero records after validation — unusable")
        if "record_count" not in output:
            return Verdict.FAIL("Missing 'record_count'")

        for i, r in enumerate(output["records"]):
            if "year" not in r or "value" not in r:
                return Verdict.FAIL(f"Record {i} missing 'year' or 'value'")
            if not isinstance(r["value"], (int, float)):
                return Verdict.FAIL(f"Record {i} value is not numeric")

        return Verdict.PASS(
            f"Validated {output['record_count']} records "
            f"from {output.get('source', 'unknown')}"
        )

    def _check_transform_to_chart(self, output: dict) -> Verdict:
        if "chart_report" not in output:
            return Verdict.FAIL(
                "Missing 'chart_report' in transform_to_chart output"
            )

        report = output["chart_report"]

        if "chart_data" not in report:
            return Verdict.FAIL("Missing 'chart_data' in chart_report")
        if "summary" not in report:
            return Verdict.FAIL("Missing 'summary' in chart_report")

        required_summary = [
            "best_year", "best_value",
            "worst_year", "worst_value",
            "avg_value", "anomalies"
        ]
        for field in required_summary:
            if field not in report["summary"]:
                return Verdict.FAIL(f"Summary missing field: '{field}'")

        for i, row in enumerate(report["chart_data"]):
            for f in ["year", "value", "yoy_change_pct"]:
                if f not in row:
                    return Verdict.FAIL(
                        f"chart_data row {i} missing field '{f}'"
                    )

        return Verdict.PASS(
            f"Chart ready: {len(report['chart_data'])} points, "
            f"best={report['summary']['best_year']}, "
            f"anomalies={len(report['summary']['anomalies'])}"
        )

    # ─────────────────────────────────────────────
    # FULL RUN VERDICT  (Scenario 1 + Scenario 2)
    # ─────────────────────────────────────────────

    def evaluate_run(self, final_state, journal) -> dict:
        """Scenario 1 full run evaluation."""
        logger.info("[Critic] Evaluating full run (Scenario 1)...")
        return self._evaluate_run_generic(
            final_state, journal,
            output_key="report",
            required_fields=["average_occupancy", "total_revenue_tnd",
                             "best_region", "anomalies"],
        )

    def evaluate_run_scenario2(self, final_state, journal) -> dict:
        """Scenario 2 full run evaluation."""
        logger.info("[Critic] Evaluating full run (Scenario 2)...")

        if "chart_report" not in final_state.tool_outputs:
            return {
                "passed": False,
                "reason": "Run ended without producing a chart_report",
                "safety_violations": [],
            }

        report = final_state.tool_outputs["chart_report"]
        if isinstance(report, dict) and "chart_report" in report:
            report = report["chart_report"]

        for field in ["chart_data", "summary"]:
            if field not in report:
                return {
                    "passed": False,
                    "reason": f"Final chart_report missing field: '{field}'",
                    "safety_violations": [],
                }

        safety_violations = [
            step for step in journal.steps
            if step["status"] == "blocked"
        ]
        if safety_violations:
            return {
                "passed": False,
                "reason": f"Run had {len(safety_violations)} security violation(s)",
                "safety_violations": safety_violations,
            }

        logger.info("[Critic] Full run Scenario 2 PASSED")
        return {
            "passed":            True,
            "reason":            "All objectives met, no safety violations",
            "safety_violations": [],
            "chart_report":      report,
        }

    def _evaluate_run_generic(
        self,
        final_state,
        journal,
        output_key: str,
        required_fields: list,
    ) -> dict:

        if output_key not in final_state.tool_outputs:
            return {
                "passed": False,
                "reason": f"Run ended without producing a {output_key}",
                "safety_violations": [],
            }

        report = final_state.tool_outputs[output_key]
        if isinstance(report, dict) and output_key in report:
            report = report[output_key]

        for field in required_fields:
            if field not in report:
                return {
                    "passed": False,
                    "reason": f"Final {output_key} missing field: '{field}'",
                    "safety_violations": [],
                }

        safety_violations = [
            step for step in journal.steps
            if step["status"] == "blocked"
        ]
        if safety_violations:
            return {
                "passed": False,
                "reason": f"Run had {len(safety_violations)} security violation(s)",
                "safety_violations": safety_violations,
            }

        logger.info("[Critic] Full run PASSED")
        return {
            "passed":            True,
            "reason":            "All objectives met, no safety violations",
            "safety_violations": [],
            "report":            report,
        }
