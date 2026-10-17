"""
tests/test_scenario2.py — Week 3 Tests
Tunisia Tourism Orchestrator

Covers:
  - Scenario 2 happy path (real or mocked World Bank API)
  - Scenario 2 injected timeout failure
  - Scenario 2 bad host blocked
  - DP cache: second call is a cache hit
  - DP cache: clear resets counters
  - validate_api_response: parses valid World Bank JSON
  - validate_api_response: rejects empty data
  - transform_to_chart: correct YoY calculation
  - transform_to_chart: detects anomaly drops
  - Concurrency: 3 parallel runs keep separate journals
  - Concurrency: DP cache shared but run journals isolated
"""

import sys
import os
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from executor import (
    Executor,
    Journal,
    _tool_validate_api_response,
    _tool_transform_to_chart,
    _tool_fetch_indicator,
    get_cache_stats,
    clear_dp_cache,
    ToolError,
    SecurityError,
)
from critic  import Critic, Verdict
from planner import PlannerState


# ─────────────────────────────────────────────
# MOCK WORLD BANK RESPONSE
# Used in all tests that don't need a real network call
# ─────────────────────────────────────────────

MOCK_WB_RESPONSE = [
    # metadata block (World Bank format)
    {"page": 1, "pages": 1, "per_page": 20, "total": 5},
    # data array
    [
        {"date": "2019", "value": 9564000.0, "country": {"id": "TN"}},
        {"date": "2020", "value": 2373000.0, "country": {"id": "TN"}},
        {"date": "2021", "value": 2973000.0, "country": {"id": "TN"}},
        {"date": "2022", "value": 6101000.0, "country": {"id": "TN"}},
        {"date": "2023", "value": 9041000.0, "country": {"id": "TN"}},
    ],
]


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_cache():
    """Clear DP cache before every test for isolation."""
    clear_dp_cache()
    yield
    clear_dp_cache()


@pytest.fixture
def run_id():
    return "test_s2_run_001"


@pytest.fixture
def journal(run_id):
    return Journal(run_id)


@pytest.fixture
def executor(run_id, journal):
    return Executor(run_id, journal)


@pytest.fixture
def critic():
    return Critic()


# ─────────────────────────────────────────────
# HELPER: build validated records from mock
# ─────────────────────────────────────────────

def _get_mock_records():
    result = _tool_validate_api_response({"raw_response": MOCK_WB_RESPONSE})
    return result["records"]


# ─────────────────────────────────────────────
# TEST 1: validate_api_response parses correctly
# ─────────────────────────────────────────────

def test_validate_api_response_parses_mock():
    result = _tool_validate_api_response({"raw_response": MOCK_WB_RESPONSE})

    assert "records" in result
    assert result["record_count"] == 5
    assert result["source"] == "World Bank"

    for r in result["records"]:
        assert "year" in r
        assert "value" in r
        assert isinstance(r["year"], int)
        assert isinstance(r["value"], float)

    # Records must be sorted ascending by year
    years = [r["year"] for r in result["records"]]
    assert years == sorted(years)


# ─────────────────────────────────────────────
# TEST 2: validate_api_response skips null values
# ─────────────────────────────────────────────

def test_validate_api_response_skips_nulls():
    raw_with_nulls = [
        {"page": 1},
        [
            {"date": "2021", "value": 2973000.0},
            {"date": "2022", "value": None},      # null — must be skipped
            {"date": "2023", "value": 9041000.0},
        ],
    ]
    result = _tool_validate_api_response({"raw_response": raw_with_nulls})
    assert result["record_count"] == 2
    years = [r["year"] for r in result["records"]]
    assert 2022 not in years


# ─────────────────────────────────────────────
# TEST 3: validate_api_response rejects empty data
# ─────────────────────────────────────────────

def test_validate_api_response_rejects_empty():
    empty_raw = [{"page": 1}, []]
    with pytest.raises(ValueError, match="0 data points"):
        _tool_validate_api_response({"raw_response": empty_raw})


# ─────────────────────────────────────────────
# TEST 4: validate_api_response rejects wrong format
# ─────────────────────────────────────────────

def test_validate_api_response_rejects_wrong_format():
    with pytest.raises((ValueError, AssertionError)):
        _tool_validate_api_response({"raw_response": {"not": "a list"}})


# ─────────────────────────────────────────────
# TEST 5: transform_to_chart correct YoY values
# ─────────────────────────────────────────────

def test_transform_to_chart_yoy_calculation():
    records = [
        {"year": 2021, "value": 2973000.0},
        {"year": 2022, "value": 6101000.0},
        {"year": 2023, "value": 9041000.0},
    ]
    result = _tool_transform_to_chart({"records": records})

    assert "chart_report" in result
    chart_data = result["chart_report"]["chart_data"]

    # First year has no YoY
    assert chart_data[0]["yoy_change_pct"] is None

    # 2022 YoY = (6101000 - 2973000) / 2973000 * 100 ≈ 105.2
    assert chart_data[1]["yoy_change_pct"] == pytest.approx(105.2, abs=0.5)

    # 2023 YoY = (9041000 - 6101000) / 6101000 * 100 ≈ 48.2
    assert chart_data[2]["yoy_change_pct"] == pytest.approx(48.2, abs=0.5)


# ─────────────────────────────────────────────
# TEST 6: transform_to_chart detects anomaly drops
# ─────────────────────────────────────────────

def test_transform_to_chart_detects_anomaly_drop():
    # 2020 had a massive drop (COVID) — should be flagged
    records = [
        {"year": 2019, "value": 9564000.0},
        {"year": 2020, "value": 2373000.0},   # big drop > 20%
        {"year": 2021, "value": 2973000.0},
    ]
    result = _tool_transform_to_chart({"records": records})
    anomalies = result["chart_report"]["summary"]["anomalies"]

    assert len(anomalies) >= 1
    anomaly_years = [a["year"] for a in anomalies]
    assert 2020 in anomaly_years


# ─────────────────────────────────────────────
# TEST 7: transform_to_chart summary fields
# ─────────────────────────────────────────────

def test_transform_to_chart_summary_fields():
    records = _get_mock_records()
    result  = _tool_transform_to_chart({"records": records})
    summary = result["chart_report"]["summary"]

    required = ["best_year", "best_value", "worst_year", "worst_value",
                "avg_value", "anomalies"]
    for field in required:
        assert field in summary, f"Summary missing field: '{field}'"

    assert summary["best_year"]  == 2019
    assert summary["worst_year"] == 2020


# ─────────────────────────────────────────────
# TEST 8: Critic validates transform_to_chart output
# ─────────────────────────────────────────────

def test_critic_accepts_valid_chart_output(critic):
    records = _get_mock_records()
    output  = _tool_transform_to_chart({"records": records})
    state   = PlannerState()
    verdict = critic.evaluate_step("transform_to_chart", output, state)
    assert verdict["passed"], f"Expected PASS but got: {verdict['reason']}"


# ─────────────────────────────────────────────
# TEST 9: Critic rejects missing chart_data
# ─────────────────────────────────────────────

def test_critic_rejects_missing_chart_data(critic):
    bad_output = {"chart_report": {"summary": {}}}
    state      = PlannerState()
    verdict    = critic.evaluate_step("transform_to_chart", bad_output, state)
    assert not verdict["passed"]
    assert "chart_data" in verdict["reason"]


# ─────────────────────────────────────────────
# TEST 10: DP cache — second call is a cache hit
# ─────────────────────────────────────────────

def test_dp_cache_hit_on_second_call(monkeypatch):
    """
    Monkeypatch httpx.get to return mock data without a real network call.
    Run fetch_indicator twice — second call must be a cache hit.
    """
    import httpx
    import executor as exe

    class MockResponse:
        status_code = 200
        content     = b"x" * 100

        def raise_for_status(self): pass
        def json(self): return MOCK_WB_RESPONSE

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: MockResponse())

    clear_dp_cache()

    # First call — cache miss
    result1 = exe._tool_fetch_indicator({
        "indicator_key": "arrivals",
        "inject_timeout": False,
    })
    assert result1["from_cache"] is False

    # Second call — must be a cache hit (no network call)
    result2 = exe._tool_fetch_indicator({
        "indicator_key": "arrivals",
        "inject_timeout": False,
    })
    assert result2["from_cache"] is True

    stats = get_cache_stats()
    assert stats["cache_hits"]   == 1
    assert stats["cache_misses"] == 1
    assert stats["hit_ratio"]    == 0.5


# ─────────────────────────────────────────────
# TEST 11: DP cache clear resets counters
# ─────────────────────────────────────────────

def test_dp_cache_clear_resets():
    import executor as exe
    exe._dp_hits   = 5
    exe._dp_misses = 3
    exe._dp_cache["fake_key"] = {"data": 1}

    clear_dp_cache()

    stats = get_cache_stats()
    assert stats["cache_hits"]   == 0
    assert stats["cache_misses"] == 0
    assert stats["cached_keys"]  == []


# ─────────────────────────────────────────────
# TEST 12: Bad host is blocked
# ─────────────────────────────────────────────

def test_bad_host_blocked(executor):
    """
    Calling fetch_indicator with a patched bad endpoint must be blocked.
    We patch WB_ENDPOINT temporarily.
    """
    import executor as exe
    original = exe.WB_ENDPOINT
    exe.WB_ENDPOINT = "https://evil-exfil.example.com/steal?indicator={indicator}"

    try:
        result = executor.run("fetch_indicator", {
            "indicator_key":  "arrivals",
            "inject_timeout": False,
        })
        assert result["status"] in ("failed", "blocked"), (
            "Expected failure when bad host is used"
        )
        error = result.get("error", "").lower()
        assert "security" in error or "allow" in error or "blocked" in error or "not in" in error
    finally:
        exe.WB_ENDPOINT = original


# ─────────────────────────────────────────────
# TEST 13: Injected timeout fails then recovers
# ─────────────────────────────────────────────

def test_injected_timeout_recovers(monkeypatch):
    """
    inject_timeout=True simulates timeout on attempts 1 and 2.
    Attempt 3 should succeed using the monkeypatched httpx.
    """
    import httpx
    import executor as exe

    class MockResponse:
        status_code = 200
        content     = b"x" * 100
        def raise_for_status(self): pass
        def json(self): return MOCK_WB_RESPONSE

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: MockResponse())
    monkeypatch.setattr(exe.time, "sleep", lambda s: None)  # skip backoff waits

    result = exe._tool_fetch_indicator({
        "indicator_key":  "arrivals",
        "inject_timeout": True,
    })

    # inject_timeout simulates failure on attempts 1 and 2, succeeds on 3
    assert result["from_cache"] is False
    assert "raw_response" in result


# ─────────────────────────────────────────────
# TEST 14: CONCURRENCY — parallel runs keep separate journals
# ─────────────────────────────────────────────

def test_concurrent_runs_separate_journals():
    """
    Launch 3 runs simultaneously using threads.
    Each run must have its own journal with its own run_id.
    No journal must contain steps from another run.
    """
    results = {}
    errors  = {}

    def run_one(run_label):
        try:
            run_id  = f"concurrent_test_{run_label}"
            journal = Journal(run_id)
            executor = Executor(run_id, journal)

            # Run a simple tool that produces a journal entry
            executor.run("read_csv", {
                "file_path":        "data_synthetic/hotels.csv",
                "expected_columns": ["region", "hotel_name", "month",
                                     "occupancy_rate", "revenue_tnd"],
            })

            results[run_label] = journal.to_dict()
        except Exception as e:
            errors[run_label] = str(e)

    threads = [
        threading.Thread(target=run_one, args=(label,))
        for label in ["A", "B", "C"]
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    # No thread should have crashed
    assert errors == {}, f"Threads raised errors: {errors}"

    # All 3 runs must have produced results
    assert len(results) == 3

    # Each journal must have its own run_id
    run_ids = [results[label]["run_id"] for label in ["A", "B", "C"]]
    assert len(set(run_ids)) == 3, "Run IDs must be unique"

    # Each journal step must belong to its own run_id only
    for label, journal_dict in results.items():
        for step in journal_dict["steps"]:
            assert step["run_id"] == journal_dict["run_id"], (
                f"Step in run {label} has foreign run_id: {step['run_id']}"
            )


# ─────────────────────────────────────────────
# TEST 15: CONCURRENCY — no state leakage between runs
# ─────────────────────────────────────────────

def test_concurrent_runs_no_step_leakage():
    """
    Each journal must contain exactly the steps from its own run.
    Count of steps must match what was expected per run.
    """
    results  = {}
    barriers = {"ready": threading.Barrier(3)}

    def run_one(label):
        run_id   = f"leak_test_{label}"
        journal  = Journal(run_id)
        executor = Executor(run_id, journal)

        # Sync all threads before starting to maximize concurrency
        barriers["ready"].wait()

        executor.run("read_csv", {
            "file_path":        "data_synthetic/hotels.csv",
            "expected_columns": ["region", "hotel_name", "month",
                                 "occupancy_rate", "revenue_tnd"],
        })
        results[label] = journal.steps

    threads = [
        threading.Thread(target=run_one, args=(label,))
        for label in ["X", "Y", "Z"]
    ]
    for t in threads: t.start()
    for t in threads: t.join(timeout=30)

    for label, steps in results.items():
        run_id = f"leak_test_{label}"
        # Every step in this journal must have the correct run_id
        for step in steps:
            assert step["run_id"] == run_id, (
                f"Run {label} journal contains step with wrong run_id: "
                f"{step['run_id']}"
            )
        # Each run called exactly 1 tool so should have exactly 1 step
        assert len(steps) == 1, (
            f"Run {label} expected 1 step but got {len(steps)}"
        )
