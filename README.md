# GUADE

Copyright (c) 2026 LeadRescue LLC. All rights reserved.

GUADE is a local-first workflow agent framework and operations dashboard. It coordinates model-backed agents through real tasks, explicit tool grants, step handoffs, local artifacts, and an auditable run history. The dashboard takes its visual direction from a sci-fi command center while operating on actual workflows and saved results.

## Requirements

- Python 3.11 or newer
- An OpenAI API key for model-backed runs
- Claude Code in the terminal only if you want Claude to launch GUADE through MCP

## Setup

1. Clone the private repository and enter the project directory:

   ```bash
   git clone https://github.com/leadrescuellc-creator/guade.git
   cd guade
   ```

2. Create and activate a Python virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

   On Windows PowerShell, activate it with `.venv\\Scripts\\Activate.ps1`.

3. Install GUADE in editable mode:

   ```bash
   python -m pip install --upgrade pip
   python -m pip install -e .
   ```

4. Set the model provider credentials in the same terminal session:

   ```bash
   export OPENAI_API_KEY="your-api-key"
   export OPENAI_MODEL="gpt-5-mini"
   ```

   For Windows PowerShell, use `$env:OPENAI_API_KEY="your-api-key"` and `$env:OPENAI_MODEL="gpt-5-mini"`. GUADE checks whether a key exists but never displays or stores its value. Runs requiring a model fail clearly when the key is missing.

5. (Optional) Choose where GUADE stores its SQLite ledger and run artifacts:

   ```bash
   export GUADE_HOME="$HOME/.guade"
   ```

   By default, run history and files are stored under `~/.guade`. Keep this data directory outside the cloned repository.

## Start The Dashboard

1. From the project directory, with the virtual environment active, start the local dashboard:

   ```bash
   guade dashboard
   ```

   You can also run it without installing the command with `python -m workflow_agent dashboard`.

2. Open [http://127.0.0.1:8765](http://127.0.0.1:8765) in your browser. The service binds to localhost by default.

3. Check the model connection indicator. If it reports a missing key, set `OPENAI_API_KEY` in the terminal that started the dashboard and restart the server.

4. Select a workflow from the library, enter the task directive, and choose **Launch workflow**. Shell tools remain disabled unless you turn on the explicit shell option for that run.

5. Select an operation in **Run history** to inspect its status, step-by-step agent outputs, and files created in the run workspace. The page refreshes active run status while work is in progress.

Stop the dashboard with `Ctrl+C` in its terminal. To use another local port, start it with `guade dashboard --port 8766` and open `http://127.0.0.1:8766`.

## Run From The Terminal

Run a workflow directly without opening the dashboard:

```bash
guade run examples/research_build.json "Research practical ways to reduce chargebacks for a small ecommerce store."
guade runs
guade show RUN_ID
```

Workflow definitions are JSON files in `examples/`. Each one declares its agents, instructions, allowed tools, and ordered steps. The included workflows are `local_builder` and `research_build`.

## Connect Claude Code In The Terminal

With Claude Code installed, run this once from the GUADE project directory:

```bash
claude mcp add guade -- /absolute/path/to/guade/bin/guade-mcp
```

For this machine's checkout, the command is:

```bash
claude mcp add guade -- /home/east/workflow-agent/bin/guade-mcp
```

Start a new Claude Code session. GUADE provides `guade_list_workflows`, `guade_run`, `guade_runs`, and `guade_show`. Claude Code must inherit `OPENAI_API_KEY` from its terminal environment for GUADE workflows that make nested model calls.

To check or remove the MCP registration, use `claude mcp list` or `claude mcp remove guade`.

## What Runs Are Saved

GUADE writes a SQLite run ledger and a directory per operation under `GUADE_HOME`. Run folders contain the workflow definition, original task, per-step prompts and outputs, agent metadata, tool call records, and files created by agents. Agent filesystem tools are scoped to the run workspace. Shell execution is disabled by default.

## Copyright And License

GUADE and its accompanying source code, documentation, dashboard, and workflow examples are proprietary to LeadRescue LLC. All rights are reserved. See [LICENSE](LICENSE) and [NOTICE](NOTICE). No license to use, copy, modify, or distribute this software is granted except as authorized in writing by LeadRescue LLC.
