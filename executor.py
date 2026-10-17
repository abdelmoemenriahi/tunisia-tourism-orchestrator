import json
import time
import uuid
import logging
import os
import hashlib
import concurrent.futures

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import httpx

logger = logging.getLogger(__name__)


# HARDENING CONSTANTS

SANDBOX_DIR = os.path.abspath("data_synthetic")
TOOL_TIMEOUT_SECONDS = 10

# allow lists
ALLOWED_BASE_PATHS = ["data_synthetic/", "data_synthetic"]

ALLOWED_TOOLS = [
    # Scenario 1
    "validate_schema",
    "read_csv",
    "compute_kpi",
    "format_output",
    # Scenario 2
    "fetch_indicator",
    "validate_api_response",
    "transform_to_chart",
]

ANOMALY_THRESHOLD = 50.0

# ============================================================
# SCENARIO 2 CONSTANTS
# ============================================================

ALLOWED_HOSTS = ["api.worldbank.org"]
MAX_RESPONSE_BYTES = 512 * 1024   # 512 KB
MAX_RETRIES_HTTP = 3

WB_ENDPOINT = (
    "https://api.worldbank.org/v2/country/TN"
    "/indicator/{indicator}"
    "?format=json&per_page=20&mrv=15"
)

TOURISM_INDICATORS = {
    "arrivals":   "ST.INT.ARVL",
    "receipts":   "ST.INT.RCPT.CD",
    "departures": "ST.INT.DPRT",
}

# DP cache (per-process, cleared between independent runs)
_dp_cache: dict = {}
_dp_hits: int = 0
_dp_misses: int = 0


def get_cache_stats() -> dict:
    total = _dp_hits + _dp_misses
    return {
        "cache_hits":   _dp_hits,
        "cache_misses": _dp_misses,
        "hit_ratio":    round(_dp_hits / total, 3) if total > 0 else 0.0,
        "cached_keys":  list(_dp_cache.keys()),
    }


def clear_dp_cache():
    """Reset DP cache — call between independent runs for concurrency safety."""
    global _dp_hits, _dp_misses
    _dp_cache.clear()
    _dp_hits = 0
    _dp_misses = 0


def _make_cache_key(indicator_key: str) -> str:
    raw = f"TN|{TOURISM_INDICATORS[indicator_key]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ============================================================
# SECURITY
# ============================================================

class SecurityError(Exception):
    pass


class ToolError(Exception):
    pass


def _check_path_allowed(path: str) -> bool:
    """Allow ONLY paths inside data_synthetic/"""
    try:
        real = os.path.realpath(os.path.abspath(path))
        allowed = (
            real.startswith(SANDBOX_DIR + os.sep)
            or real == SANDBOX_DIR
        )
        if not allowed:
            logger.warning(
                "PATH BLOCKED: %r resolves to %r outside sandbox %r",
                path, real, SANDBOX_DIR
            )
        return allowed
    except Exception as exc:
        logger.warning("PATH CHECK ERROR: %s", exc)
        return False


def _check_host_allowed(url: str) -> bool:
    """Allow ONLY hosts in ALLOWED_HOSTS."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        allowed = host in ALLOWED_HOSTS
        if not allowed:
            logger.warning(
                "HOST BLOCKED: %r not in allow-list %r",
                host, ALLOWED_HOSTS
            )
        return allowed
    except Exception as exc:
        logger.warning("HOST CHECK ERROR: %s", exc)
        return False


# ============================================================
# TIMEOUT WRAPPER
# ============================================================

def _run_tool_with_timeout(tool_fn, *args, **kwargs):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(tool_fn, *args, **kwargs)
        try:
            return future.result(timeout=TOOL_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(
                f"Tool '{tool_fn.__name__}' exceeded "
                f"{TOOL_TIMEOUT_SECONDS}s timeout"
            )


# ============================================================
# SCENARIO 1 — INPUT VALIDATORS
# ============================================================

def _validate_read_csv_input(inp: dict):
    assert "file_path" in inp
    assert "expected_columns" in inp
    assert isinstance(inp["file_path"], str)
    assert isinstance(inp["expected_columns"], list)
    assert len(inp["expected_columns"]) > 0


def _validate_compute_kpi_input(inp: dict):
    assert "records" in inp
    assert isinstance(inp["records"], list)
    assert len(inp["records"]) > 0
    for r in inp["records"]:
        assert "occupancy_rate" in r
        assert "revenue_tnd" in r
        assert "region" in r
        assert "hotel_name" in r


def _validate_format_output_input(inp: dict):
    assert "kpis" in inp
    required = [
        "average_occupancy",
        "total_revenue_tnd",
        "best_region",
        "anomalies"
    ]
    for f in required:
        assert f in inp["kpis"]


def _validate_validate_schema_input(inp: dict):
    assert "file_path" in inp
    assert "expected_columns" in inp


# ============================================================
# SCENARIO 2 — INPUT VALIDATORS
# ============================================================

def _validate_fetch_indicator_input(inp: dict):
    assert "indicator_key" in inp, "Missing 'indicator_key'"
    assert inp["indicator_key"] in TOURISM_INDICATORS, (
        f"indicator_key must be one of {list(TOURISM_INDICATORS.keys())}"
    )


def _validate_validate_api_response_input(inp: dict):
    assert "raw_response" in inp, "Missing 'raw_response'"
    assert isinstance(inp["raw_response"],
                      list), "'raw_response' must be a list"
    assert len(inp["raw_response"]) == 2, (
        "World Bank JSON must be [metadata, data_array]"
    )


def _validate_transform_to_chart_input(inp: dict):
    assert "records" in inp, "Missing 'records'"
    assert isinstance(inp["records"], list), "'records' must be a list"
    assert len(inp["records"]) > 0, "No records to transform"
    for r in inp["records"]:
        assert "year" in r, "Each record needs 'year'"
        assert "value" in r, "Each record needs 'value'"


# ============================================================
# SCENARIO 1 — TOOLS
# ============================================================

def _tool_validate_schema(inp: dict) -> dict:
    if not _check_path_allowed(inp["file_path"]):
        raise PermissionError(
            f"SECURITY_VIOLATION: path outside sandbox: "
            f"{inp['file_path']}"
        )
    path = Path(inp["file_path"])
    if not path.exists():
        raise ToolError(f"File not found: {inp['file_path']}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    missing = set(inp["expected_columns"]) - set(header)
    if missing:
        raise ToolError(f"Missing columns: {missing}")
    return {
        "schema_valid": True,
        "columns_found": header
    }


def _tool_read_csv(inp: dict) -> dict:
    if not _check_path_allowed(inp["file_path"]):
        raise PermissionError(
            f"SECURITY_VIOLATION: path outside sandbox: "
            f"{inp['file_path']}"
        )
    path = Path(inp["file_path"])
    if not path.exists():
        raise ToolError(f"File not found: {inp['file_path']}")
    try:
        df = pd.read_csv(path)
    except Exception as e:
        raise ToolError(f"Failed to read CSV: {e}")
    missing = set(inp["expected_columns"]) - set(df.columns.tolist())
    if missing:
        raise ToolError(f"Missing columns: {missing}")
    try:
        df["occupancy_rate"] = df["occupancy_rate"].astype(float)
        df["revenue_tnd"] = df["revenue_tnd"].astype(float)
    except Exception as e:
        raise ToolError(f"Type validation failed: {e}")
    invalid_occ = df[
        (df["occupancy_rate"] < 0)
        | (df["occupancy_rate"] > 100)
    ]
    if not invalid_occ.empty:
        raise ToolError(
            f"occupancy_rate invalid rows: "
            f"{invalid_occ.index.tolist()}"
        )
    invalid_rev = df[df["revenue_tnd"] < 0]
    if not invalid_rev.empty:
        raise ToolError(
            f"negative revenue rows: "
            f"{invalid_rev.index.tolist()}"
        )
    records = df.to_dict(orient="records")
    return {
        "records": records,
        "row_count": len(records)
    }


def _tool_compute_kpi(inp: dict) -> dict:
    records = inp["records"]
    avg_occupancy = (
        sum(r["occupancy_rate"] for r in records)
        / len(records)
    )
    total_revenue = sum(r["revenue_tnd"] for r in records)
    region_revenue = {}
    for r in records:
        region_revenue[r["region"]] = (
            region_revenue.get(r["region"], 0)
            + r["revenue_tnd"]
        )
    best_region = max(region_revenue, key=region_revenue.get)
    anomalies = [
        {
            "hotel": r["hotel_name"],
            "occupancy": r["occupancy_rate"]
        }
        for r in records
        if r["occupancy_rate"] < ANOMALY_THRESHOLD
    ]
    kpis = {
        "average_occupancy": round(avg_occupancy, 2),
        "total_revenue_tnd": round(total_revenue, 2),
        "best_region": best_region,
        "anomalies": anomalies
    }
    return {"kpis": kpis}


def _tool_format_output(inp: dict) -> dict:
    kpis = inp["kpis"]
    if not (0 <= kpis["average_occupancy"] <= 100):
        raise ToolError("average_occupancy invalid")
    if kpis["total_revenue_tnd"] < 0:
        raise ToolError("negative revenue")
    report = {
        "average_occupancy": kpis["average_occupancy"],
        "total_revenue_tnd": kpis["total_revenue_tnd"],
        "best_region": kpis["best_region"],
        "anomalies": kpis["anomalies"]
    }
    return {"report": report}


# ============================================================
# SCENARIO 2 — TOOLS
# ============================================================

def _tool_fetch_indicator(inp: dict) -> dict:
    """
    HTTP GET World Bank indicator for Tunisia.
    - Host allow-list check
    - DP cache lookup before any network call
    - Bounded retry with exponential backoff
    - inject_timeout flag for failure injection
    """
    global _dp_hits, _dp_misses

    indicator_key = inp["indicator_key"]
    inject_timeout = inp.get("inject_timeout", False)
    indicator_code = TOURISM_INDICATORS[indicator_key]
    url = WB_ENDPOINT.format(indicator=indicator_code)

    # SECURITY CHECK
    if not _check_host_allowed(url):
        raise PermissionError(
            f"SECURITY_VIOLATION: host not in allow-list: {url}"
        )

    # DP CACHE LOOKUP
    cache_key = _make_cache_key(indicator_key)
    if cache_key in _dp_cache:
        _dp_hits += 1
        logger.info(
            "[DP] Cache HIT key=%s indicator=%s hits=%d misses=%d",
            cache_key, indicator_key, _dp_hits, _dp_misses
        )
        return {**_dp_cache[cache_key], "from_cache": True}

    _dp_misses += 1
    logger.info(
        "[DP] Cache MISS key=%s indicator=%s hits=%d misses=%d",
        cache_key, indicator_key, _dp_hits, _dp_misses
    )

    # BOUNDED RETRY LOOP
    last_error = None
    for attempt in range(1, MAX_RETRIES_HTTP + 1):

        # FAILURE INJECTION
        if inject_timeout and attempt <= 2:
            logger.warning(
                "[INJECT] Simulating timeout on attempt %d/%d",
                attempt, MAX_RETRIES_HTTP
            )
            last_error = TimeoutError(
                f"INJECTED_TIMEOUT on attempt {attempt}"
            )
            backoff = 2 ** (attempt - 1)
            logger.info("Retry %d/%d after %ss backoff...",
                        attempt, MAX_RETRIES_HTTP, backoff)
            time.sleep(backoff)
            continue

        try:
            logger.info(
                "HTTP GET attempt %d/%d → %s",
                attempt, MAX_RETRIES_HTTP, url
            )
            response = httpx.get(
                url,
                timeout=TOOL_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
            response.raise_for_status()

            if len(response.content) > MAX_RESPONSE_BYTES:
                raise ValueError(
                    f"Response too large: {len(response.content)} bytes"
                )

            raw = response.json()
            result = {
                "raw_response":   raw,
                "indicator_key":  indicator_key,
                "indicator_code": indicator_code,
                "http_status":    response.status_code,
                "from_cache":     False,
            }

            # STORE IN DP CACHE
            _dp_cache[cache_key] = result
            logger.info("[DP] Stored in cache key=%s", cache_key)
            return result

        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            last_error = exc
            backoff = 2 ** (attempt - 1)
            logger.warning(
                "Attempt %d/%d failed: %s. Backoff %ss.",
                attempt, MAX_RETRIES_HTTP, exc, backoff
            )
            if attempt < MAX_RETRIES_HTTP:
                time.sleep(backoff)

    raise TimeoutError(
        f"fetch_indicator failed after {MAX_RETRIES_HTTP} attempts. "
        f"Last error: {last_error}"
    )


def _tool_validate_api_response(inp: dict) -> dict:
    """
    Parse World Bank JSON [metadata, data_array].
    Extract clean {year, value} records, skip nulls, sort ascending.
    """
    raw = inp["raw_response"]

    if not isinstance(raw, list) or len(raw) != 2:
        raise ValueError(
            "World Bank response must be [metadata, data_array]"
        )

    data_array = raw[1]
    if not isinstance(data_array, list):
        raise ValueError("data_array (raw[1]) must be a list")
    if len(data_array) == 0:
        raise ValueError("API returned 0 data points for TN")

    records = []
    for entry in data_array:
        year = entry.get("date")
        value = entry.get("value")
        if year is None or value is None:
            continue
        try:
            records.append({
                "year":  int(year),
                "value": float(value),
            })
        except (TypeError, ValueError):
            logger.warning("Skipping malformed entry: %s", entry)
            continue

    if len(records) == 0:
        raise ValueError("No valid numeric records found after parsing")

    records.sort(key=lambda r: r["year"])

    logger.info(
        "validate_api_response: %d valid records extracted", len(records)
    )

    return {
        "records":      records,
        "record_count": len(records),
        "source":       "World Bank",
    }


def _tool_transform_to_chart(inp: dict) -> dict:
    """
    Compute year-over-year % change.
    Detect anomalies (YoY drop > 20%).
    Return chart-ready JSON.
    """
    records = inp["records"]

    chart_data = []
    for i, rec in enumerate(records):
        year = rec["year"]
        value = rec["value"]
        if i == 0:
            yoy = None
        else:
            prev = records[i - 1]["value"]
            yoy = round((value - prev) / prev * 100, 2) if prev != 0 else None
        chart_data.append({
            "year":           year,
            "value":          value,
            "yoy_change_pct": yoy,
        })

    values = [r["value"] for r in records]
    best = max(records, key=lambda r: r["value"])
    worst = min(records, key=lambda r: r["value"])
    avg = round(sum(values) / len(values), 2)

    anomalies = [
        {"year": row["year"], "yoy_change_pct": row["yoy_change_pct"]}
        for row in chart_data
        if row["yoy_change_pct"] is not None
        and row["yoy_change_pct"] < -20
    ]

    report = {
        "chart_data": chart_data,
        "summary": {
            "best_year":   best["year"],
            "best_value":  best["value"],
            "worst_year":  worst["year"],
            "worst_value": worst["value"],
            "avg_value":   avg,
            "anomalies":   anomalies,
        },
    }

    logger.info(
        "transform_to_chart: %d points, best=%s, anomalies=%d",
        len(chart_data), best["year"], len(anomalies)
    )

    return {"chart_report": report}


# ============================================================
# TOOL REGISTRY
# ============================================================

TOOL_VALIDATORS = {
    # Scenario 1
    "validate_schema":       _validate_validate_schema_input,
    "read_csv":              _validate_read_csv_input,
    "compute_kpi":           _validate_compute_kpi_input,
    "format_output":         _validate_format_output_input,
    # Scenario 2
    "fetch_indicator":       _validate_fetch_indicator_input,
    "validate_api_response": _validate_validate_api_response_input,
    "transform_to_chart":    _validate_transform_to_chart_input,
}

TOOL_FUNCTIONS = {
    # Scenario 1
    "validate_schema": _tool_validate_schema,
    "read_csv":        _tool_read_csv,
    "compute_kpi":     _tool_compute_kpi,
    "format_output":   _tool_format_output,
    # Scenario 2
    "fetch_indicator":       _tool_fetch_indicator,
    "validate_api_response": _tool_validate_api_response,
    "transform_to_chart":    _tool_transform_to_chart,
}


# ============================================================
# JOURNAL
# ============================================================

class Journal:

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.steps = []

    def log(
        self,
        step_id,
        tool,
        inp,
        output,
        status,
        error,
        latency_ms
    ):
        # Redact raw_response from logs (never log full API payload)
        safe_inp = {
            k: v for k, v in inp.items()
            if k != "raw_response"
        }

        entry = {
            "run_id":     self.run_id,
            "step_id":    step_id,
            "tool":       tool,
            "input":      safe_inp,
            "output":     output,
            "status":     status,
            "error":      error,
            "latency_ms": latency_ms,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }

        self.steps.append(entry)

        logger.info(
            f"[Journal] {status.upper()} | "
            f"{tool} | {latency_ms}ms"
        )

        return entry

    def to_dict(self):
        return {
            "run_id": self.run_id,
            "steps": self.steps
        }

    def save(self, path: str):
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


# ============================================================
# EXECUTOR
# ============================================================

class Executor:

    def __init__(self, run_id: str, journal: Journal):
        self.run_id = run_id
        self.journal = journal
        self._step_counter = 0

    def run(self, tool_name: str, tool_input: dict):

        self._step_counter += 1
        step_id = f"step_{self._step_counter:03d}"
        start = time.monotonic()

        logger.info(
            f"[Executor] Running tool '{tool_name}' "
            f"(step {step_id})"
        )

        if tool_name not in ALLOWED_TOOLS:
            error = f"Tool '{tool_name}' is not on the allow-list"
            self.journal.log(
                step_id, tool_name, tool_input,
                None, "blocked", error, 0
            )
            return {"status": "blocked", "error": error}

        validator = TOOL_VALIDATORS.get(tool_name)

        try:
            validator(tool_input)
        except AssertionError as e:
            error = f"Input validation failed: {e}"
            self.journal.log(
                step_id, tool_name, tool_input,
                None, "failed", error, 0
            )
            return {"status": "failed", "error": error}

        fn = TOOL_FUNCTIONS[tool_name]

        try:
            output = _run_tool_with_timeout(fn, tool_input)
        except PermissionError as e:
            error = str(e)
            latency = int((time.monotonic() - start) * 1000)
            self.journal.log(
                step_id, tool_name, tool_input,
                None, "blocked", error, latency
            )
            return {"status": "blocked", "error": error}
        except Exception as e:
            error = str(e)
            latency = int((time.monotonic() - start) * 1000)
            self.journal.log(
                step_id, tool_name, tool_input,
                None, "failed", error, latency
            )
            return {"status": "failed", "error": error}

        latency = int((time.monotonic() - start) * 1000)
        self.journal.log(
            step_id, tool_name, tool_input,
            output, "success", None, latency
        )

        return {"status": "success", "output": output}
