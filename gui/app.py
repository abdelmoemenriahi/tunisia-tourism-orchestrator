"""
gui/app.py — Tunisia Tourism Orchestrator Dashboard
Week 3: Scenario 2 wired in, DP cache stats, failure injection controls
"""

import json
import streamlit as st
from pathlib import Path

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

st.set_page_config(page_title="Tunisia Tourism Orchestrator", layout="wide")

st.markdown("""
<style>
.stApp {
             background-color: #050508; 
            color: #f0ecff;
            }
[data-testid="stSidebar"] {
             background-color: #080714;
             border-right: 1px solid #3b2e6e;
             }
[data-testid="stSidebar"] * { 
            color: #e8e0ff !important; 
            }
h1 { 
            color: #d8b4fe !important; 
            font-weight: 700; }
h2 {
             color: #c4b5fd !important; }
h3 { color: #a78bfa !important; }
[data-testid="stMetric"] { background-color: #0f0d28;
             border: 1px solid #5b3fd4;
             border-radius: 10px; 
            padding: 16px; }
[data-testid="stMetricLabel"] {
             color: #d4c8f8 !important; 
            font-size: 13px; }
[data-testid="stMetricValue"] { 
            color: #ffffff !important;
             font-size: 26px; 
            font-weight: 700; }
.stButton > button { background-color: #7c3aed;
             color: #ffffff;
             border: none; border-radius: 8px;
             padding: 10px 24px;
             font-weight: 600; }
.stButton > button:hover { 
            background-color: #6d28d9;
             color: #ffffff; 
            }
[data-testid="stSelectbox"] > div > div {
             background-color: #0f0d28;
             border: 1px solid #5b3fd4;
             color: #f0ecff;
             border-radius: 8px; }
[data-testid="stExpander"] { 
            background-color: #0a0920;
             border: 1px solid #3b2e6e;
             border-radius: 8px; 
            margin-bottom: 6px; }
[data-testid="stExpander"] summary { 
            color: #e2d9ff !important;
             font-weight: 500; }
hr { border-color: #3b2e6e; }
code { background-color: #0f0d28 !important;
             color: #d8b4fe !important;
             border-radius: 6px; }
label { color: #e8e0ff !important; }
.card { background-color: #0f0d28; 
            border: 1px solid #5b3fd4;
             border-radius: 10px;
             padding: 20px; 
            margin-bottom: 16px; }
.badge-success {
             background-color: #14532d;
             color: #bbf7d0; 
            padding: 2px 10px; 
            border-radius: 12px;
             font-size: 12px; 
            font-weight: 600; }
.badge-failed { background-color: #7f1d1d; 
            color: #fecaca;
             padding: 2px 10px;
             border-radius: 12px; 
            font-size: 12px; 
            font-weight: 600; }
.badge-blocked { background-color: #78350f; 
            color: #fde68a;
             padding: 2px 10px;
             border-radius: 12px;
             font-size: 12px;
            font-weight: 600; }
.sidebar-title { 
            font-size: 18px;
             font-weight: 700; 
            color: #d8b4fe; 
            margin-bottom: 20px;
             padding-bottom: 10px; 
            border-bottom: 1px solid #3b2e6e; }
p, li, span { color: #e8e0ff; }
.stCaption { color: #b8b0d8 !important; }
[data-testid="stDataFrame"] { border: 1px solid #3b2e6e;
             border-radius: 8px; }
html, body, [class*="css"],*,:not(h1, h2, h3, h4, h5, h6){
    font-family: "JetBrains Mono", monospace;
}
</style>
""", unsafe_allow_html=True)

st.sidebar.markdown(
    '<div class="sidebar-title">Tunisia Tourism Orchestrator</div>', unsafe_allow_html=True)
page = st.sidebar.radio("Menu", [
                        "Run & Trace", "Metrics", "Safety & Rules", "About"], label_visibility="collapsed")



# step timeline renderer


def render_step_timeline(steps):
    st.subheader("What the system did — step by step")
    for step in steps:
        badge = {
            "success": '<span class="badge-success">done</span>',
            "failed":  '<span class="badge-failed">failed</span>',
            "blocked": '<span class="badge-blocked">blocked</span>',
        }.get(step["status"], step["status"])

        with st.expander(f"Step {step['step_id']}  |  {step['tool']}  |  {step['latency_ms']} ms"):
            st.markdown(f"Status: {badge}", unsafe_allow_html=True)
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Input sent to the tool**")
                st.json(step["input"])
            with col2:
                st.markdown("**Result from the tool**")
                if step["output"]:
                    st.json(step["output"])
                elif step["error"]:
                    st.error(step["error"])


def render_final_check(result):
    st.subheader("Final Check")
    if result["status"] == "failed":
        st.error(
            f"Run stopped early — {result.get('error', 'see step timeline above')}")
        return

    check = result["critic_verdict"]
    if check["passed"]:
        st.success(f"Passed — {check['reason']}")
    else:
        st.error(f"Did not pass — {check['reason']}")

    if check.get("safety_violations"):
        st.warning("Some actions were blocked for safety reasons:")
        st.dataframe(check["safety_violations"])


# RUN & TRACE

if page == "Run & Trace":
    st.title("Run & Trace")
    st.caption("Pick a scenario, choose a test mode, and start the system.")

    col1, col2 = st.columns([2, 1])
    with col1:
        scenario = st.selectbox("Scenario", [
            "Scenario 1 — Hotel Data Dashboard",
            "Scenario 2 — Tunisia Tourism API Indicators",
        ])

        if "Scenario 1" in scenario:
            test_mode = st.selectbox("Test mode", [
                "Normal run",
                "Simulate missing column error",
            ])
        else:
            test_mode = st.selectbox("Test mode", [
                "Normal run",
                "Simulate API timeout",
            ])
            indicator = st.selectbox("Indicator", [
                "arrivals",
                "receipts",
                "departures",
            ])

    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        run_button = st.button("Start", type="primary",
                               use_container_width=True)

    st.divider()

    # ── Trigger run ──
    if run_button:
        with st.spinner("Running..."):
            try:
                if "Scenario 1" in scenario:
                    from run_manager import run_scenario1
                    injection = "missing_column" if "missing column" in test_mode else None
                    result = run_scenario1(
                        "data_synthetic/hotels.csv", failure_injection=injection)
                    st.session_state["last_result"] = result
                    st.session_state["last_scenario"] = 1

                else:
                    from run_manager import run_scenario2
                    inject_timeout = "timeout" in test_mode
                    result = run_scenario2(
                        indicator_key=indicator,
                        inject_timeout=inject_timeout,
                    )
                    st.session_state["last_result"] = result
                    st.session_state["last_scenario"] = 2

            except Exception as e:
                st.error(f"Something went wrong: {e}")

    # ── Show results ──
    if "last_result" in st.session_state:
        result = st.session_state["last_result"]
        scenario_num = st.session_state.get("last_scenario", 1)

        st.subheader("Run Overview")
        status_label = "Completed" if result["status"] == "success" else "Failed"
        col1, col2, col3 = st.columns(3)
        col1.metric("Result",     status_label)
        col2.metric("Steps used", result["steps_taken"])
        col3.metric("Retries",    result["retries"])

        st.divider()

        # ── Scenario 1 report ──
        if scenario_num == 1:
            if result["status"] == "success" and result["report"]:
                st.subheader("Hotel Performance Report")
                report = result["report"]
                col1, col2, col3 = st.columns(3)
                col1.metric("Average Occupancy",
                            f"{report['average_occupancy']}%")
                col2.metric("Total Revenue",
                            f"{report['total_revenue_tnd']:,.0f} TND")
                col3.metric("Top Region",        report["best_region"])

                if report["anomalies"]:
                    st.warning(
                        f"{len(report['anomalies'])} hotel(s) have low occupancy (below 50%)")
                    st.dataframe(report["anomalies"], use_container_width=True)
                else:
                    st.success(
                        "All hotels are performing above the minimum threshold.")

            elif result["status"] == "failed":
                st.error(f"Run stopped: {result['error']}")

        # ── Scenario 2 report ──
        else:
            # DP cache stats
            dp = result.get("dp_cache_stats", {})
            if dp:
                st.subheader("Cache Stats (DP Memoization)")
                c1, c2, c3 = st.columns(3)
                c1.metric("Cache Hits",   dp.get("cache_hits", 0))
                c2.metric("Cache Misses", dp.get("cache_misses", 0))
                c3.metric("Hit Ratio",    dp.get("hit_ratio", 0))

            if result["status"] == "success" and result["report"]:
                chart_report = result["report"]
                if isinstance(chart_report, dict) and "chart_report" in chart_report:
                    chart_report = chart_report["chart_report"]

                st.subheader("Tunisia Tourism Indicator Report")

                summary = chart_report.get("summary", {})
                c1, c2, c3 = st.columns(3)
                c1.metric("Best Year",    summary.get("best_year", "N/A"))
                c2.metric("Worst Year",   summary.get("worst_year", "N/A"))
                c3.metric(
                    "Average",      f"{summary.get('avg_value', 0):,.0f}")

                # Chart-ready data table
                chart_data = chart_report.get("chart_data", [])
                if chart_data:
                    import pandas as pd
                    df = pd.DataFrame(chart_data)
                    df.columns = ["Year", "Visitor Arrivals",
                                  "Year-on-Year Change (%)"]
                    st.dataframe(df, use_container_width=True)

                    # Line chart
                    st.line_chart(df.set_index("Year")["Visitor Arrivals"])

                anomalies = summary.get("anomalies", [])
                if anomalies:
                    st.warning(
                        f"{len(anomalies)} year(s) had a drop of more than 20% compared to the previous year")
                    st.dataframe(anomalies, use_container_width=True)
                else:
                    st.success("No major drops detected in the series.")

            elif result["status"] == "failed":
                st.error(f"Run stopped: {result['error']}")

        st.divider()
        render_step_timeline(result["journal"]["steps"])
        st.divider()
        render_final_check(result)


#  METRICS


elif page == "Metrics":
    st.title("Metrics & Complexity Analysis")
    st.caption("Per-run table, BT vs DP comparison, DP cache hit ratio, and latency stats.")

    import pandas as pd
    import plotly.graph_objects as go
    from complexity_analysis import get_metrics_for_gui, get_run_table_rows

    data = get_metrics_for_gui(Path("logs"))
    runs = data["runs"]
    M    = data["summary"]
    TS   = data["tools"]

    if not runs:
        st.info("No runs yet. Go to 'Run & Trace' and start a run first.")
    else:
        # ── Top KPI strip ──
        st.subheader("Session Summary")
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Total runs",      M["n_runs"])
        c2.metric("Success rate",    f"{M['success_rate']}%")
        c3.metric("Avg latency",     f"{M['avg_lat']} ms")
        c4.metric("P95 latency",     f"{M['p95_lat']} ms")
        c5.metric("DP cache hits",   f"{int(M['hit_ratio']*100)}%")
        c6.metric("Prune rate",      f"{M['prune_rate']}%")

        st.divider()

        # ── Per-run table ──
        st.subheader("Per-Run Table")
        st.caption("Steps taken, branches explored, branches pruned, avg latency, P95 latency, total run time.")
        rows = get_run_table_rows(runs)
        if rows:
            df_runs = pd.DataFrame(rows)
            st.dataframe(df_runs, use_container_width=True)

        st.divider()

        # ── BT-only vs BT+DP chart ─────────────────────────────────────
        st.subheader("BT-only vs BT+DP — Latency Comparison")
        st.caption("Required by Section 8. Same tasks, different planning mode.")

        bt_runs = [r for r in runs if r["mode"] == "BT-only"][:15]
        dp_runs = [r for r in runs if r["mode"] == "BT+DP"][:15]

        fig_cmp = go.Figure()
        if bt_runs:
            fig_cmp.add_trace(go.Bar(
                name="BT-only",
                x=[r["run_id"] for r in bt_runs],
                y=[r["total_ms"] for r in bt_runs],
                marker_color="#ff6b8a",
            ))
        if dp_runs:
            fig_cmp.add_trace(go.Bar(
                name="BT+DP",
                x=[r["run_id"] for r in dp_runs],
                y=[r["total_ms"] for r in dp_runs],
                marker_color="#00c9b1",
            ))
        fig_cmp.update_layout(
            barmode="group",
            paper_bgcolor="#0d1117",
            plot_bgcolor="#161b22",
            font=dict(color="#e6edf3", size=11),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
            yaxis_title="Total run time (ms)",
            height=320,
            margin=dict(l=40, r=20, t=20, b=40),
        )
        fig_cmp.update_xaxes(gridcolor="#21262d")
        fig_cmp.update_yaxes(gridcolor="#21262d")
        st.plotly_chart(fig_cmp, use_container_width=True)

        # Summary comparison table
        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("BT-only avg run", f"{M['bt_avg']} ms", help=f"{M['n_bt']} runs")
        with col_b:
            st.metric("BT+DP avg run", f"{M['dp_avg']} ms",
                      delta=f"-{M['bt_avg']-M['dp_avg']} ms vs BT-only",
                      delta_color="normal",
                      help=f"{M['n_dp']} runs")

        st.divider()

        # ── DP Cache hit ratio ───
        st.subheader("DP Cache Hit Ratio (per run)")
        st.caption("Scenario 2 runs only — shows whether fetch_indicator returned from cache.")

        s2_runs = [r for r in runs if r["scenario"] == 2]
        if s2_runs:
            fig_cache = go.Figure()
            ids    = [r["run_id"] for r in s2_runs]
            hits   = [1 if r["dp_cache_hit"] else 0 for r in s2_runs]
            colors = ["#00c9b1" if h else "#ff6b8a" for h in hits]
            fig_cache.add_trace(go.Bar(
                x=ids, y=hits, marker_color=colors,
                text=["HIT" if h else "MISS" for h in hits],
                textposition="outside",
            ))
            fig_cache.update_layout(
                paper_bgcolor="#0d1117", plot_bgcolor="#161b22",
                font=dict(color="#e6edf3", size=11),
                yaxis=dict(tickvals=[0, 1], ticktext=["MISS", "HIT"], gridcolor="#21262d"),
                xaxis=dict(gridcolor="#21262d"),
                height=240, margin=dict(l=40, r=20, t=10, b=40),
            )
            st.plotly_chart(fig_cache, use_container_width=True)

            c1, c2, c3 = st.columns(3)
            total_s2 = len(s2_runs)
            hit_count = sum(1 for r in s2_runs if r["dp_cache_hit"])
            c1.metric("S2 runs", total_s2)
            c2.metric("Cache hits", hit_count)
            c3.metric("Hit ratio", f"{int(hit_count/max(total_s2,1)*100)}%")
        else:
            st.info("No Scenario 2 runs yet. Run 'python run_manager.py s2_normal' first.")

        st.divider()

        # ── Tool latency table ───
        st.subheader("Tool Latency Breakdown")
        if TS:
            df_tools = pd.DataFrame(TS)
            df_tools.columns = ["Tool", "Scenario", "Count", "Avg ms",
                                 "P95 ms", "Min ms", "Max ms", "Std"]
            st.dataframe(df_tools, use_container_width=True)

        st.divider()

        # ── Terminal commands ─────
        st.subheader("Terminal Commands")
        col1, col2 = st.columns(2)
        with col1:
            st.caption("Full complexity report (all runs):")
            st.code("python complexity_analysis.py complexity")
        with col2:
            st.caption("DP benchmark (cold vs warm cache):")
            st.code("python run_manager.py s2_benchmark")

#  SAFETY & RULES


elif page == "Safety & Rules":
    st.title("Safety & Rules")
    st.caption("Rules that the system follows to stay safe and predictable.")

    st.subheader("Allowed file locations")
    st.code("data_synthetic/")
    st.caption(
        "The system can only read files from this folder. Anything outside is blocked.")

    st.subheader("Allowed API hosts")
    st.code("api.worldbank.org")
    st.caption(
        "The system can only call this host. Any other URL is blocked before the request is sent.")

    st.subheader("Allowed tools")
    st.code("validate_schema\nread_csv\ncompute_kpi\nformat_output\nfetch_indicator\nvalidate_api_response\ntransform_to_chart")

    st.subheader("Run limits")
    col1, col2, col3 = st.columns(3)
    col1.metric("Max steps per run", 10)
    col2.metric("Max retries",       2)
    col3.metric("Tool timeout",      "10s")

    st.subheader("Blocked actions (all runs)")
    logs_dir = Path("logs")
    run_files = list(logs_dir.glob("run_*.json")) if logs_dir.exists() else []
    blocked = []
    for f in run_files:
        try:
            data = json.loads(f.read_text())
            for step in data.get("steps", []):
                if step["status"] == "blocked":
                    blocked.append({
                        "Run":    data["run_id"],
                        "Tool":   step["tool"],
                        "Reason": step["error"],
                        "Time":   step["timestamp"],
                    })
        except Exception:
            continue

    if blocked:
        import pandas as pd
        st.dataframe(pd.DataFrame(blocked), use_container_width=True)
    else:
        st.success("No blocked actions recorded.")


# ABOUT


elif page == "About":
    st.title("About")

    st.markdown("""
    <div class="card">
        <b>Project:</b> Tourism Data Orchestrator for Tunisia<br><br>
        <b>Course:</b> Problem Solving — 2BIS 2025-2026<br><br>
        <b>Professor:</b> Chaouki Bayoudhi
    </div>
    """, unsafe_allow_html=True)

    st.subheader("Group Members")
    st.markdown("""
    - Riahi Abdelmoemen
    - Assidi Amr
    - Azzi Moenes
    - Sdiri Med Aziz
    """)

    st.subheader("What this system does")
    st.markdown("""
    This system uses three agents that work together to process tourism data from Tunisia:

    - **Planner** — decides which steps to take and what to do if something goes wrong
    - **Executor** — runs each step, checks inputs and outputs, and keeps a log of everything
    - **Critic** — checks if the final result is correct and safe before approving it

    **Scenario 1** reads a local file of hotel records, computes performance numbers by region,
    and produces a structured report.

    **Scenario 2** calls the World Bank API to get real Tunisia tourism indicators,
    validates the response, and produces a chart-ready summary with year-on-year changes.

    If a step fails, the system tries an alternative approach before stopping.
    Results are cached so repeated requests do not hit the API again.
    """)
