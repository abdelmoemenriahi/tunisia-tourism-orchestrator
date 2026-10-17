"""
tests/test_scenario1.py — Week 2 Tests for Scenario 1
Tunisia Tourism Orchestrator

Covers:
  - Happy path (full run succeeds, report is correct)
  - Injected failure: missing column (system stops safely)
  - Security: path outside sandbox is blocked
  - Security: unknown tool is blocked
  - Critic: catches bad KPI values
  - Critic: catches missing report fields
"""

import pytest
import sys
import os

# Make sure imports work from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from executor import Executor, Journal, SecurityError, ToolError
from critic   import Critic, Verdict
from planner  import Planner, PlannerState
from run_manager import run_scenario1


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def run_id():
    return "test_run_001"

@pytest.fixture
def journal(run_id):
    return Journal(run_id)

@pytest.fixture
def executor(run_id, journal):
    return Executor(run_id, journal)

@pytest.fixture
def critic():
    return Critic()

@pytest.fixture
def planner():
    return Planner()


# ─────────────────────────────────────────────
# TEST 1: Happy Path — full run succeeds
# ─────────────────────────────────────────────

def test_scenario1_happy_path():
    """Full Scenario 1 run with valid CSV should succeed and return all KPI fields."""
    result = run_scenario1("data_synthetic/hotels.csv")

    assert result["status"] == "success", f"Expected success but got: {result['error']}"
    assert result["report"] is not None

    report = result["report"]
    assert "average_occupancy"  in report
    assert "total_revenue_tnd"  in report
    assert "best_region"        in report
    assert "anomalies"          in report

    # Value range checks
    assert 0 <= report["average_occupancy"] <= 100
    assert report["total_revenue_tnd"] > 0
    assert isinstance(report["anomalies"], list)

    # All anomalies should have occupancy < 50
    for anomaly in report["anomalies"]:
        assert anomaly["occupancy"] < 50, (
            f"Anomaly has occupancy >= 50: {anomaly}"
        )


# ─────────────────────────────────────────────
# TEST 2: Injected Failure — missing column
# ─────────────────────────────────────────────

def test_missing_column_stops_safely():
    """
    When the CSV is missing an expected column, the system must:
    - NOT crash with an unhandled exception
    - Return status = "failed"
    - Include a clear error message mentioning the missing column
    """
    result = run_scenario1(
        "data_synthetic/hotels.csv",
        failure_injection="missing_column",
    )

    assert result["status"] == "failed", (
        "Expected failure but got success — missing column was not caught"
    )
    assert result["error"] is not None
    assert "Missing columns" in result["error"] or "missing" in result["error"].lower(), (
        f"Error message does not mention missing columns: {result['error']}"
    )
    # Report should NOT be produced when run fails
    assert result["report"] is None or result["report"] == {}


# ─────────────────────────────────────────────
# TEST 3: Security — path outside sandbox is blocked
# ─────────────────────────────────────────────

def test_path_outside_sandbox_blocked(executor):
    """Trying to read a file outside the allowed sandbox must be blocked."""
    result = executor.run("read_csv", {
        "file_path": "../../etc/passwd",
        "expected_columns": ["region"],
    })
    assert result["status"] == "blocked", (
        f"Expected 'blocked' but got '{result['status']}'"
    )
    assert "sandbox" in result["error"].lower() or "security" in result["error"].lower()


def test_absolute_path_blocked(executor):
    """Absolute paths must also be blocked."""
    result = executor.run("read_csv", {
        "file_path": "/etc/passwd",
        "expected_columns": ["region"],
    })
    assert result["status"] == "blocked"


# ─────────────────────────────────────────────
# TEST 4: Security — unknown tool is blocked
# ─────────────────────────────────────────────

def test_unknown_tool_blocked(executor):
    """Calling a tool not on the allow-list must be blocked."""
    result = executor.run("delete_all_files", {"target": "/"})
    assert result["status"] == "blocked"
    assert "allow-list" in result["error"].lower()


# ─────────────────────────────────────────────
# TEST 5: Executor — read_csv validates missing column
# ─────────────────────────────────────────────

def test_read_csv_catches_missing_column(executor):
    """read_csv must fail (not crash) when a required column is absent."""
    result = executor.run("read_csv", {
        "file_path": "data_synthetic/hotels.csv",
        "expected_columns": ["region", "hotel_name", "NONEXISTENT_COLUMN"],
    })
    assert result["status"] == "failed"
    assert "Missing columns" in result["error"] or "NONEXISTENT_COLUMN" in result["error"]


# ─────────────────────────────────────────────
# TEST 6: Executor — read_csv succeeds with valid file
# ─────────────────────────────────────────────

def test_read_csv_success(executor):
    """read_csv must return records when file and columns are valid."""
    result = executor.run("read_csv", {
        "file_path": "data_synthetic/hotels.csv",
        "expected_columns": ["region", "hotel_name", "month", "occupancy_rate", "revenue_tnd"],
    })
    assert result["status"] == "success"
    assert "records" in result["output"]
    assert len(result["output"]["records"]) > 0


# ─────────────────────────────────────────────
# TEST 7: Executor — compute_kpi produces correct values
# ─────────────────────────────────────────────

def test_compute_kpi_correct_values(executor):
    """compute_kpi must compute correct KPIs from known records."""
    records = [
        {"region": "Sousse",   "hotel_name": "Hotel A", "month": "January", "occupancy_rate": 80.0, "revenue_tnd": 100000},
        {"region": "Djerba",   "hotel_name": "Hotel B", "month": "January", "occupancy_rate": 90.0, "revenue_tnd": 200000},
        {"region": "Monastir", "hotel_name": "Hotel C", "month": "January", "occupancy_rate": 40.0, "revenue_tnd": 50000},
    ]
    result = executor.run("compute_kpi", {"records": records})

    assert result["status"] == "success"
    kpis = result["output"]["kpis"]

    # avg = (80 + 90 + 40) / 3 = 70.0
    assert abs(kpis["average_occupancy"] - 70.0) < 0.1

    # total revenue = 350000
    assert kpis["total_revenue_tnd"] == 350000

    # best region = Djerba (highest revenue = 200000)
    assert kpis["best_region"] == "Djerba"

    # anomalies = Hotel C (occupancy 40.0 < 50)
    assert len(kpis["anomalies"]) == 1
    assert kpis["anomalies"][0]["hotel"] == "Hotel C"


# ─────────────────────────────────────────────
# TEST 8: Critic — catches bad KPI values
# ─────────────────────────────────────────────

def test_critic_rejects_out_of_range_occupancy(critic):
    """Critic must reject KPIs where average_occupancy is out of [0, 100]."""
    bad_output = {
        "kpis": {
            "average_occupancy": 150.0,   # invalid
            "total_revenue_tnd": 500000,
            "best_region": "Djerba",
            "anomalies": [],
        }
    }
    state = PlannerState()
    verdict = critic.evaluate_step("compute_kpi", bad_output, state)
    assert not verdict["passed"]
    assert "range" in verdict["reason"].lower() or "out of" in verdict["reason"].lower()


def test_critic_rejects_negative_revenue(critic):
    """Critic must reject KPIs where total_revenue_tnd is negative."""
    bad_output = {
        "kpis": {
            "average_occupancy": 70.0,
            "total_revenue_tnd": -1000,   # invalid
            "best_region": "Djerba",
            "anomalies": [],
        }
    }
    state = PlannerState()
    verdict = critic.evaluate_step("compute_kpi", bad_output, state)
    assert not verdict["passed"]


# ─────────────────────────────────────────────
# TEST 9: Critic — accepts valid KPIs
# ─────────────────────────────────────────────

def test_critic_accepts_valid_kpis(critic):
    """Critic must pass valid KPI output."""
    good_output = {
        "kpis": {
            "average_occupancy": 70.7,
            "total_revenue_tnd": 484000,
            "best_region": "Djerba",
            "anomalies": [{"hotel": "Hotel Monastir D", "occupancy": 43.5}],
        }
    }
    state = PlannerState()
    verdict = critic.evaluate_step("compute_kpi", good_output, state)
    assert verdict["passed"], f"Expected PASS but got: {verdict['reason']}"


# ─────────────────────────────────────────────
# TEST 10: Journal — every step is logged
# ─────────────────────────────────────────────

def test_journal_logs_every_step():
    """Every tool call must produce a journal entry."""
    result = run_scenario1("data_synthetic/hotels.csv")
    journal = result["journal"]

    assert "steps" in journal
    assert len(journal["steps"]) > 0

    for step in journal["steps"]:
        assert "tool"       in step
        assert "status"     in step
        assert "timestamp"  in step
        assert "latency_ms" in step


# ─────────────────────────────────────────────
# TEST 11: Journal — failure injection is logged
# ─────────────────────────────────────────────

def test_journal_logs_failure_injection():
    """When a tool fails, the journal must record it with status 'failed'."""
    result = run_scenario1(
        "data_synthetic/hotels.csv",
        failure_injection="missing_column",
    )
    journal = result["journal"]
    failed_steps = [s for s in journal["steps"] if s["status"] == "failed"]
    assert len(failed_steps) > 0, "Expected at least one failed step in journal"
