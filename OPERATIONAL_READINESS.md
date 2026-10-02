# GUADE operational readiness

Checked 2026-10-02 using Main Player plus live host verification.

## Verified live

- GUADE dashboard is reachable at `http://127.0.0.1:8765`.
- GUADE status reports workflow provider ready: `ollama` using `qwen3.5:9b`.
- GUADE assistant provider is `codex`.
- Media tools are ready.
- OpenClaw gateway is running as an enabled user service on `127.0.0.1:18789`.
- OpenClaw model route resolves to `openai/gpt-5.5` with `codex` as the agent runtime.
- OpenClaw OpenAI auth route is usable through the stored API-key profile.
- GUADE has an `OpenClaw` MCP connector configured over stdio.
- GUADE successfully inspected OpenClaw and found 9 MCP tools.
- A GUADE workflow agent granted `mcp.openclaw` successfully received all 9 OpenClaw tool schemas.
- A live OpenClaw MCP call to `conversations_list` succeeded through GUADE's connector path.
- All 7 workflow definitions load successfully.
- Multi-agent workflow inventory is available:
  - `research-build-review`: 3 agents, 3 steps.
  - `competitor-intelligence`: 3 agents, 3 steps.
  - `game-preproduction-blueprint`: 3 agents, 3 steps.
  - `income-opportunity-scan`: 3 agents, 3 steps.
  - `sales-output`: 3 agents, 3 steps.
  - `shop-setup-kit`: 3 agents, 3 steps.
  - `local-builder`: 2 agents, 2 steps.

## Main Player result

The in-app Main Player accepted the command to set up, configure, and play GUADE. It wrote this readiness file and confirmed the project test/workflow definitions from inside its restricted Codex sandbox. Its sandbox could not perform live network/listener checks, so host-level verification above reconciles the actual runtime state.

## Operational status

GUADE is operational locally with Codex as Main Player, Ollama as workflow model provider, OpenClaw connected as a callable MCP connector, and multiple workflow agents available. OpenClaw gateway capability reports `read-only` because no command owner is paired, but GUADE can read OpenClaw conversations/events and respond to OpenClaw permission prompts through MCP.

## Remaining watch items

- OpenClaw gateway auth is set to `none` and bound to loopback only. This is intentional for local GUADE integration; keep `gateway.bind=loopback`.
- OpenClaw reports an expired OAuth profile, but the active API-key profile is usable.
- The restored OpenClaw config still contains legacy channel/plugin state. It is functioning, but `openclaw doctor` should be run after major OpenClaw upgrades.
- Screen recording is active until stopped by command.

## Commander next move

Run or inspect a multi-agent mission in the GUADE dashboard at `http://127.0.0.1:8765`. For OpenClaw-aware missions, grant the `OpenClaw` connector to the workflow agent that needs it.
