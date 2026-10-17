# Tunisia Tourism Orchestrator

A Python project that demonstrates a tool-based multi-agent workflow for tourism-data analysis in Tunisia. It combines planning, tool execution, result validation, run journaling, failure scenarios, and a Streamlit dashboard.

> **Academic project:** developed for the Problem Solving course (2BIS, 2025–2026). The project uses synthetic hotel records for Scenario 1 and the World Bank API for Scenario 2. It is a course project, not a production tourism service.

Please describe your own contribution accurately when presenting this team project.

## Features

- **Planner:** selects an ordered tool plan and has fallback/backtracking logic.
- **Executor:** runs approved tools, validates inputs, applies path/host restrictions, and records tool calls.
- **Critic:** checks run results and safety-related conditions.
- **Two scenarios:** local synthetic hotel data and tourism indicators from the World Bank API.
- **Failure demonstrations:** missing-column and simulated API-timeout cases.
- **Caching and benchmarking:** demonstrates dynamic-programming cache behavior and compares cold/warm runs.
- **Observability:** JSON run journals, a Streamlit interface, and a complexity/latency report.
- **Automated tests:** tests for successful runs, failure handling, validation, security restrictions, caching, and concurrency.

## Architecture

```text
User / Streamlit UI
        |
        v
   Run Manager
        |
        v
     Planner  ------> fallback plan when appropriate
        |
        v
     Executor ------> local CSV / World Bank API
        |                      |
        v                      v
   Run journal <--------- tool results
        |
        v
      Critic
        |
        v
   Final status + report
```

## Project structure

```text
.
├── planner.py
├── executor.py
├── critic.py
├── run_manager.py
├── complexity_analysis.py
├── data_synthetic/
│   └── hotels.csv
├── gui/
│   └── app.py
├── tests/
│   ├── test_scenario1.py
│   └── test_scenario2.py
├── docs/
│   └── design_document.docx
├── requirements.txt
├── .gitignore
└── README.md
```

Generated run journals are written to `logs/` and intentionally excluded from Git to keep the repository small and avoid committing machine-specific run output.

## Requirements

- Python 3.10 or newer recommended
- Internet connection for Scenario 2's World Bank API call

## Setup

Run these commands from the repository root.

### Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Run scenarios

Run commands from the repository root.

| Command | Purpose |
|---|---|
| `python run_manager.py normal` | Scenario 1: analyze synthetic hotel CSV data |
| `python run_manager.py inject` | Scenario 1: demonstrate missing-column failure handling |
| `python run_manager.py security` | Scenario 1: demonstrate a blocked file-path attempt |
| `python run_manager.py s2_normal` | Scenario 2: fetch tourism indicators from the World Bank API |
| `python run_manager.py s2_inject` | Scenario 2: simulate timeout/retry behavior |
| `python run_manager.py s2_security` | Scenario 2: demonstrate a blocked API-host attempt |
| `python run_manager.py s2_benchmark` | Compare cold and warm cache runs |

Scenario 2 requires internet access and depends on the external API being reachable.

## Launch the dashboard

```bash
python -m streamlit run gui/app.py
```

The Streamlit app includes run tracing, metrics, safety/rule information, and project details. Start it from the repository root so relative data and log paths resolve as expected.

## Run tests

```bash
python -m pytest tests/ -v
```

The current test suite contains 28 tests across the two scenarios. Tests should be run locally before submitting changes; external API behavior can vary, so check the output in your environment.

## Complexity report

After generating run journals, use:

```bash
python complexity_analysis.py complexity
python complexity_analysis.py dashboard
```

The dashboard command generates `complexity_analysis.html` from available local run logs. This generated HTML file is excluded from version control.

## Data and privacy

- `data_synthetic/hotels.csv` contains synthetic sample data for the local scenario.
- Scenario 2 requests tourism indicators from the World Bank API.
- Do not commit API keys, credentials, personal data, or private logs.

## Limitations

- The application is a teaching/demo project and is not intended for production use.
- Scenario 2 depends on the availability and structure of an external API.
- Test success demonstrates the tested cases only; it does not prove the system is free of defects.

## License

This project is distributed under the MIT License. See [LICENSE](LICENSE) for the full terms.
