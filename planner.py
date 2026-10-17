from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# ============================================================
# SCENARIO 1 PLANS
# ============================================================

SCENARIO1_TOOLS    = ["read_csv", "compute_kpi", "format_output"]
SCENARIO1_FALLBACK = ["validate_schema", "read_csv", "compute_kpi", "format_output"]

# ============================================================
# SCENARIO 2 PLANS
# ============================================================

SCENARIO2_TOOLS    = ["fetch_indicator", "validate_api_response", "transform_to_chart"]
SCENARIO2_FALLBACK = ["fetch_indicator", "validate_api_response", "transform_to_chart"]


# ============================================================
# PLANNER STATE
# ============================================================

@dataclass
class PlannerState:
    completed_tools: list          = field(default_factory=list)
    tool_outputs:    dict          = field(default_factory=dict)
    steps_taken:     int           = 0
    retries:         int           = 0
    using_fallback:  bool          = False
    last_error:      Optional[str] = None


MAX_STEPS   = 10
MAX_RETRIES = 2


# ============================================================
# FEASIBILITY CHECK  (Scenario 1 + Scenario 2 rules)
# ============================================================

def is_feasible(tool_name: str, state: PlannerState, task: dict) -> tuple[bool, str]:

    if state.steps_taken >= MAX_STEPS:
        return False, f"Step budget exhausted ({MAX_STEPS} steps max)"

    if state.retries >= MAX_RETRIES:
        return False, f"Retry budget exhausted ({MAX_RETRIES} retries max)"

    if tool_name in state.completed_tools:
        return False, f"Tool '{tool_name}' already completed successfully"

    # ── Scenario 1 rules ────────────────────────────────────
    if tool_name == "read_csv":
        if "file_path" not in task:
            return False, "Task is missing 'file_path' for read_csv"

    if tool_name == "compute_kpi":
        if "read_csv" not in state.completed_tools and \
           "validate_schema" not in state.completed_tools:
            return False, "compute_kpi requires read_csv to complete first"
        if "records" not in state.tool_outputs:
            return False, "No records found in state for compute_kpi"

    if tool_name == "format_output":
        if "compute_kpi" not in state.completed_tools:
            return False, "format_output requires compute_kpi to complete first"
        if "kpis" not in state.tool_outputs:
            return False, "No kpis found in state for format_output"

    # ── Scenario 2 rules ────────────────────────────────────
    if tool_name == "fetch_indicator":
        if "indicator_key" not in task:
            return False, "Task is missing 'indicator_key' for fetch_indicator"

    if tool_name == "validate_api_response":
        if "fetch_indicator" not in state.completed_tools:
            return False, "validate_api_response requires fetch_indicator first"
        if "raw_response" not in state.tool_outputs:
            return False, "No raw_response in state for validate_api_response"

    if tool_name == "transform_to_chart":
        if "validate_api_response" not in state.completed_tools:
            return False, "transform_to_chart requires validate_api_response first"
        if "records" not in state.tool_outputs:
            return False, "No records in state for transform_to_chart"

    return True, ""


# ============================================================
# OUTPUT KEY
# ============================================================

def _output_key(tool_name: str) -> str:
    mapping = {
        # Scenario 1
        "validate_schema":       "schema_valid",
        "read_csv":              "records",
        "compute_kpi":           "kpis",
        "format_output":         "report",
        # Scenario 2
        "fetch_indicator":       "raw_response",
        "validate_api_response": "records",
        "transform_to_chart":    "chart_report",
    }
    return mapping.get(tool_name, tool_name)


# ============================================================
# BUILD TOOL INPUT
# ============================================================

def _build_tool_input(tool_name: str, state: PlannerState, task: dict) -> dict:

    # ── Scenario 1 ──────────────────────────────────────────
    if tool_name == "validate_schema":
        return {
            "file_path":        task["file_path"],
            "expected_columns": task["expected_columns"],
        }

    if tool_name == "read_csv":
        return {
            "file_path":        task["file_path"],
            "expected_columns": task["expected_columns"],
        }

    if tool_name == "compute_kpi":
        raw = state.tool_outputs["records"]
        if isinstance(raw, dict) and "records" in raw:
            raw = raw["records"]
        return {"records": raw}

    if tool_name == "format_output":
        raw = state.tool_outputs["kpis"]
        if isinstance(raw, dict) and "kpis" in raw:
            raw = raw["kpis"]
        return {"kpis": raw}

    # ── Scenario 2 ──────────────────────────────────────────
    if tool_name == "fetch_indicator":
        return {
            "indicator_key":  task["indicator_key"],
            "inject_timeout": task.get("inject_timeout", False),
        }

    if tool_name == "validate_api_response":
        raw = state.tool_outputs["raw_response"]
        if isinstance(raw, dict) and "raw_response" in raw:
            raw = raw["raw_response"]
        return {"raw_response": raw}

    if tool_name == "transform_to_chart":
        raw = state.tool_outputs["records"]
        if isinstance(raw, dict) and "records" in raw:
            raw = raw["records"]
        return {"records": raw}

    return {}


# ============================================================
# OBJECTIVES CHECK
# ============================================================

def _all_objectives_met(state: PlannerState, scenario: int = 1) -> bool:
    if scenario == 1:
        return (
            "format_output" in state.completed_tools
            and "report" in state.tool_outputs
        )
    elif scenario == 2:
        return (
            "transform_to_chart" in state.completed_tools
            and "chart_report" in state.tool_outputs
        )
    return False


# ============================================================
# FAILURE HANDLER
# ============================================================

def _handle_failure(
    failed_tool: str,
    error_msg: str,
    remaining_tools: list,
    state: PlannerState,
    task: dict,
    executor,
    critic,
    scenario: int = 1,
) -> tuple[bool, PlannerState]:

    state.last_error = error_msg
    state.retries += 1

    if state.retries > MAX_RETRIES:
        logger.error("Planner: max retries reached, stopping safely.")
        return False, state

    fallback = SCENARIO1_FALLBACK if scenario == 1 else SCENARIO2_FALLBACK

    if not state.using_fallback:
        logger.info("Planner: switching to fallback plan and backtracking.")
        state.using_fallback = True
        fallback_remaining = [
            t for t in fallback
            if t not in state.completed_tools
        ]
        return backtrack(
            fallback_remaining, state, task, executor, critic, scenario
        )
    else:
        logger.error("Planner: fallback also failed, stopping safely.")
        return False, state


# ============================================================
# BACKTRACKING
# ============================================================

def backtrack(
    plan:     list,
    state:    PlannerState,
    task:     dict,
    executor,
    critic,
    scenario: int = 1,
) -> tuple[bool, PlannerState]:

    if not plan:
        if _all_objectives_met(state, scenario):
            logger.info("Planner: all objectives met, plan complete.")
            return True, state
        else:
            logger.warning("Planner: plan exhausted but objectives not fully met.")
            return False, state

    if state.steps_taken >= MAX_STEPS or state.retries >= MAX_RETRIES:
        logger.warning("Planner: budget exhausted, pruning this branch.")
        return False, state

    next_tool       = plan[0]
    remaining_tools = plan[1:]

    logger.info(
        f"Planner: considering tool '{next_tool}' "
        f"(step {state.steps_taken + 1}/{MAX_STEPS})"
    )

    feasible, reason = is_feasible(next_tool, state, task)
    if not feasible:
        logger.warning(f"Planner: tool '{next_tool}' is not feasible — {reason}")
        return backtrack(remaining_tools, state, task, executor, critic, scenario)

    state.steps_taken += 1
    tool_input = _build_tool_input(next_tool, state, task)

    logger.info(f"▶️  Planner: calling Executor with tool '{next_tool}'")
    result = executor.run(next_tool, tool_input)

    if result["status"] == "success":
        state.completed_tools.append(next_tool)
        state.tool_outputs[_output_key(next_tool)] = result["output"]
        state.last_error = None

        logger.info(f"Planner: tool '{next_tool}' succeeded")

        verdict = critic.evaluate_step(next_tool, result["output"], state)
        if not verdict["passed"]:
            logger.warning(
                f"Critic rejected step '{next_tool}': {verdict['reason']}"
            )
            return _handle_failure(
                next_tool, verdict["reason"], remaining_tools,
                state, task, executor, critic, scenario
            )

        return backtrack(remaining_tools, state, task, executor, critic, scenario)

    else:
        error_msg = result.get("error", "unknown error")
        logger.warning(f"Planner: tool '{next_tool}' failed — {error_msg}")
        return _handle_failure(
            next_tool, error_msg, remaining_tools,
            state, task, executor, critic, scenario
        )


# ============================================================
# PLANNER CLASS
# ============================================================

class Planner:

    def run(self, task: dict, executor, critic) -> dict:
        """Run Scenario 1 (CSV KPI chain)."""

        logger.info(f"Planner starting Scenario 1 — task: {task}")

        initial_state = PlannerState()
        success, final_state = backtrack(
            plan     = list(SCENARIO1_TOOLS),
            state    = initial_state,
            task     = task,
            executor = executor,
            critic   = critic,
            scenario = 1,
        )

        return self._build_result(success, final_state, output_key="report")

    def run_scenario2(self, task: dict, executor, critic) -> dict:
        """Run Scenario 2 (World Bank API chain)."""

        logger.info(f"Planner starting Scenario 2 — task: {task}")

        initial_state = PlannerState()
        success, final_state = backtrack(
            plan     = list(SCENARIO2_TOOLS),
            state    = initial_state,
            task     = task,
            executor = executor,
            critic   = critic,
            scenario = 2,
        )

        return self._build_result(success, final_state, output_key="chart_report")

    def _build_result(
        self,
        success: bool,
        final_state: PlannerState,
        output_key: str,
    ) -> dict:

        if success:
            return {
                "status": "success",
                "report": final_state.tool_outputs.get(output_key),
                "state":  final_state,
            }
        elif (
            final_state.last_error
            and "SECURITY_VIOLATION" in final_state.last_error
        ):
            return {
                "status": "security_stop",
                "error":  final_state.last_error,
                "report": None,
                "state":  final_state,
            }
        else:
            return {
                "status": "failed",
                "error":  final_state.last_error or "Plan could not be completed",
                "report": None,
                "state":  final_state,
            }
