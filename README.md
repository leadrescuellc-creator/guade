# GUADE

Copyright (c) 2026 LeadRescue LLC. All rights reserved.

GUADE is a local-first workflow agent framework and operations dashboard. It coordinates model-backed agents through real tasks, explicit tool grants, step handoffs, local artifacts, and an auditable run history. The dashboard takes its visual direction from a sci-fi command center while operating on actual workflows and saved results.

## Requirements

- Python 3.11 or newer
- Ollama, Codex CLI, or an OpenAI API key, depending on selected provider
- Claude Code in the terminal only if you want Claude to launch GUADE through MCP
- FFmpeg and ffprobe for the video clipping studio

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

4. Choose providers in the dashboard's **Chat with GUADE** panel. Workflow runs default to local Ollama (`qwen3.5:9b`); install Ollama and pull the model if needed. OpenAI API mode requires credentials in the dashboard process environment:

   ```bash
   export OPENAI_API_KEY="your-api-key"
   export OPENAI_MODEL="gpt-5-mini"
   ```

   For Windows PowerShell, use `$env:OPENAI_API_KEY="your-api-key"` and `$env:OPENAI_MODEL="gpt-5-mini"`. API keys are never entered into the dashboard or saved in provider settings. Direct chat supports Codex CLI, Ollama, or OpenAI API. Workflow agents support Ollama or OpenAI-compatible Responses API providers; Codex CLI is chat-only because tool-granted workflows use the Responses tool-calling contract.

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

3. Check the model connection indicator. Ollama must be running for local workflow models. If you select OpenAI API, set `OPENAI_API_KEY` in the environment that starts GUADE. Codex chat uses the signed-in Codex CLI and does not need that API key.

4. Select a workflow from the library, enter the task directive, and choose **Launch workflow**. Shell tools remain disabled unless you turn on the explicit shell option for that run.

5. Select an operation in **Run history** to inspect its status, step-by-step agent outputs, and files created in the run workspace. The page refreshes active run status while work is in progress.

6. To use **Creator Studio**, install FFmpeg from [ffmpeg.org](https://ffmpeg.org/download.html), restart GUADE, upload footage you own or are licensed to use, choose a time range and aspect ratio, then render a clip. Set a frame time and headline to save a PNG thumbnail. Media stays under `GUADE_HOME/media`.

Stop the dashboard with `Ctrl+C` in its terminal. To use another local port, start it with `guade dashboard --port 8766` and open `http://127.0.0.1:8766`.

## Chat And Model Providers

Use **Chat with GUADE** for setup questions, connector guidance, workflow directions, and terminal commands. Its conversation is held in that browser's local storage. Select Codex CLI for a signed-in, ephemeral, read-only assistant session; select Ollama for local chat; or select OpenAI API if you have an API key. Commands are suggested for you to review and run, never executed by chat.

Workflow agents use Ollama or the OpenAI Responses API. Ollama is the default workflow provider and model on a fresh install. Start the Ollama service and pull the configured model if it is not already present:

```bash
ollama pull qwen3.5:9b
```

The dashboard's model settings let you change provider, model name, and compatible API base URL. To use Codex CLI for chat, install it, sign in with `codex login`, then restart GUADE. Codex CLI is not offered for tool-using workflow runs; those use the Responses API function-calling contract.

## Open GUADE Like A Desktop App

On Linux, install a GUADE launcher in the applications menu and (when available) on the Desktop:

```bash
python3 bin/install-guade-desktop
```

Click **GUADE** to start the local dashboard and open it in an app-style Chromium window. Python and the project checkout must remain installed in place. You can also start it directly with `bin/guade-desktop`.

Provider choices and model names are stored in `GUADE_HOME/provider-settings.json` with owner-only file permissions. Ollama defaults to `http://127.0.0.1:11434/v1`; select a model shown by `ollama list`. Codex chat requires the Codex CLI to be installed and signed in (`codex login status`).

## Run From The Terminal

Run a workflow directly without opening the dashboard:

```bash
guade run examples/research_build.json "Research practical ways to reduce chargebacks for a small ecommerce store."
guade runs
guade show RUN_ID
```

Workflow definitions are JSON files in `examples/`. Each one declares its agents, instructions, allowed tools, and ordered steps. The included `income_opportunity_scan` ranks ideas against a user's skills and constraints, while `shop_setup_kit` builds a platform-ready store, product, service, or Fiverr gig package. `competitor_intelligence`, `sales_output`, `local_builder`, and `research_build` cover research and production tasks. Income recommendations are hypotheses until validated against current market evidence.

## Find An Income Path And Prepare A Shop

1. In the dashboard's **Income desk**, enter your skills, available hours, startup budget, audience, and existing channels. This profile is stored in that browser only.
2. Choose **Build opportunity map** to rank possible income paths and create validation steps. Include public source URLs in the task or connect a search MCP tool to the opportunity agent for live research.
3. Choose **Build shop launch kit** or **Build Fiverr gig kit** to create profile text, listing copy, service tiers, pricing assumptions, FAQs, image briefs, and platform setup checklists.
4. Review the saved package in the operation details. Replace placeholders with verified facts, then publish through the platform account or a connected platform tool.
5. Use **Creator Studio** to prepare owned footage as clips and thumbnails for service listings or social channels.

GUADE does not promise earnings or claim to open accounts or publish listings automatically. It prepares reviewable work before you spend money or publish.

## Connect Agent Tools

GUADE accepts local stdio and remote HTTP MCP tool servers, so you can connect tools needed by different agents without adding vendor-specific code.

1. Set any API keys in the terminal that will start GUADE. For example, set `MY_SEARCH_KEY` to the key required by your MCP server. Secret values are not entered into the dashboard or saved in the connector file.
2. Open **Connections**, choose local process or remote endpoint, then enter a unique connector ID, display name, command and arguments or HTTPS endpoint, and environment or HTTP-header mappings such as `SEARCH_API_KEY=MY_SEARCH_KEY`.
3. Save the connector and choose **Inspect tools**. GUADE starts the configured server and lists its tools. Missing environment variables are shown by name only.
4. In **New operation**, choose which configured servers each workflow agent may use. Grants apply to that agent and run. Workflow JSON can also grant `mcp.CONNECTOR_ID` for all server tools or `mcp.CONNECTOR_ID.tool_name` for a single tool.
5. Restart GUADE after changing terminal environment variables. Connector definitions are stored in `GUADE_HOME/mcp-connectors.json`; they contain commands and variable names, never secret values.

MCP servers run with the operating-system permissions of the GUADE process. Register servers you trust and grant each one only to agents that need it.

## Payments And Business Identity

The **Payments & business** area groups MCP connectors for payment processors, banking/data providers, crypto wallet tools, and authorized EIN or D-U-N-S workflows. These are provider connector slots, not built-in integrations or payment execution. Use a provider with its own authorization and confirmation flow, inspect its MCP tools, then grant only the narrow access needed. GUADE does not accept bank passwords, account numbers, wallet seed phrases, or private keys, and does not store EIN or D-U-N-S values in connector settings.

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
