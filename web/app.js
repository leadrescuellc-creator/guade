// Copyright (c) 2026 LeadRescue LLC. All rights reserved.
const $ = (selector) => document.querySelector(selector);
const state = { workflows: [], runs: [], connectors: [], catalog: [], opportunities: [], catalogTimer: null, terminalSession: null, terminalTimer: null, selectedWorkflow: null, selectedRun: null, pollTimer: null, sourceFile: null, sourceId: null, sourceDuration: 0, sourceUrl: null, mediaReady: false };
let pendingChatActions = [];

const chatKey = "guade-assistant-chat";
let chatMessages = [];
try {
  const stored = JSON.parse(localStorage.getItem(chatKey) || "[]");
  if (Array.isArray(stored)) chatMessages = stored.filter((item) => ["user", "assistant"].includes(item?.role) && typeof item.content === "string").slice(-16);
} catch {}

function renderChat() {
  const container = $("#assistant-messages");
  if (!chatMessages.length) {
    container.innerHTML = '<div class="assistant-welcome"><span class="assistant-mark">G</span><div><strong>GUADE Main Player</strong><p>Tell me the objective. I can pick workflows, operate the board, and edit project files through Codex when you ask.</p></div></div>';
    return;
  }
  container.innerHTML = chatMessages.map((message) => `<article class="chat-message ${message.role === "user" ? "chat-user" : "chat-agent"}"><span class="chat-speaker">${message.role === "user" ? "YOU" : "GUADE ASSISTANT"}</span><div class="chat-content"></div></article>`).join("");
  container.querySelectorAll(".chat-content").forEach((node, index) => { node.textContent = chatMessages[index].content; });
  container.scrollTop = container.scrollHeight;
}

function renderChatActions(actions = pendingChatActions) {
  pendingChatActions = actions;
  const area = $("#assistant-actions");
  area.replaceChildren();
  for (const action of actions) {
    const card = document.createElement("article");
    card.className = "chat-action-card";
    const heading = document.createElement("strong");
    heading.textContent = `GUADE suggests changing ${action.path}`;
    const summary = document.createElement("p");
    summary.textContent = action.summary || "Review the proposed change. Nothing has been changed yet.";
    const diff = document.createElement("pre");
    diff.textContent = action.diff || "New file content prepared.";
    const buttons = document.createElement("div");
    buttons.className = "chat-action-buttons";
    const apply = document.createElement("button");
    apply.type = "button";
    apply.className = "button-primary";
    apply.textContent = "Apply change";
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "chat-action-dismiss";
    dismiss.textContent = "Don't apply";
    apply.addEventListener("click", async () => {
      apply.disabled = true;
      try {
        const result = await request(`/api/chat/actions/${encodeURIComponent(action.approval_id)}/approve`, { method: "POST" });
        summary.textContent = `Done. Changed ${result.path}.`;
        diff.remove();
        buttons.remove();
        pendingChatActions = pendingChatActions.filter((item) => item.approval_id !== action.approval_id);
      } catch (error) {
        summary.textContent = error.message;
        apply.disabled = false;
      }
    });
    dismiss.addEventListener("click", () => {
      card.remove();
      pendingChatActions = pendingChatActions.filter((item) => item.approval_id !== action.approval_id);
    });
    buttons.append(apply, dismiss);
    card.append(heading, summary, diff, buttons);
    area.append(card);
  }
}

const assistantSection = $("#assistant");
const assistantToggle = $("#assistant-toggle");
function setAssistantOpen(open) {
  assistantSection.classList.toggle("assistant-collapsed", !open);
  assistantToggle.setAttribute("aria-expanded", String(open));
  assistantToggle.querySelector(".assistant-toggle-state").textContent = open ? "MINIMIZE" : "OPEN";
  try { localStorage.setItem("guade-assistant-open", String(open)); } catch {}
}
setAssistantOpen(localStorage.getItem("guade-assistant-open") === "true");
assistantToggle.addEventListener("click", () => setAssistantOpen(assistantSection.classList.contains("assistant-collapsed")));

function updateProviderFields() {
  const assistant = $("#assistant-provider").value;
  $("#assistant-base-url").disabled = assistant === "codex";
  $("#assistant-base-url").placeholder = assistant === "codex" ? "Not used by Codex CLI" : "API base URL (optional)";
  const workflow = $("#workflow-provider").value;
  $("#workflow-base-url").placeholder = workflow === "ollama" ? "http://127.0.0.1:11434/v1" : "https://api.openai.com/v1";
}

async function loadProviderSettings() {
  try {
    const settings = await request("/api/settings/provider");
    for (const scope of ["workflow", "assistant"]) {
      $(`#${scope}-provider`).value = settings[scope].provider;
      $(`#${scope}-model`).value = settings[scope].model;
      $(`#${scope}-base-url`).value = settings[scope].base_url;
    }
    updateProviderFields();
    document.querySelectorAll("[data-setup-provider]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.setupProvider === settings.assistant.provider));
    });
    updateSetupHelp(settings.assistant.provider);
  } catch (error) {
    $("#provider-message").textContent = error.message;
  }
}

function updateSetupHelp(provider) {
  const help = {
    codex: "Codex selected. Make sure Codex CLI is installed and signed in. Your current workflow model stays as-is.",
    ollama: "Ollama selected. Install Ollama and download a model first. GUADE will use it for chat and workflows.",
    openai: "OpenAI selected. Set OPENAI_API_KEY in the terminal before starting GUADE. The key is never stored in this screen.",
  };
  $("#setup-choice-help").textContent = help[provider] || "Choose A, B, or C to see what you need.";
  $("#setup-save").disabled = !provider;
}

document.querySelectorAll("[data-setup-provider]").forEach((button) => button.addEventListener("click", () => {
  const choice = button.dataset.setupProvider;
  $("#assistant-provider").value = choice;
  if (choice === "ollama" || choice === "openai") $("#workflow-provider").value = choice;
  updateProviderFields();
  document.querySelectorAll("[data-setup-provider]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
  updateSetupHelp(choice);
}));
$("#setup-save").addEventListener("click", () => $("#provider-settings-form").requestSubmit());

$("#workflow-provider").addEventListener("change", updateProviderFields);
$("#assistant-provider").addEventListener("change", updateProviderFields);
$("#provider-settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#provider-save");
  const message = $("#provider-message");
  button.disabled = true;
  try {
    await request("/api/settings/provider", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(["workflow", "assistant"].map((scope) => [scope, {
        provider: $(`#${scope}-provider`).value,
        model: $(`#${scope}-model`).value.trim(),
        base_url: $(`#${scope}-base-url`).value.trim(),
      }]))),
    });
    message.textContent = "Saved locally. New chat replies and workflow runs will use these providers.";
    $("#setup-choice-help").textContent = "Choice saved on this computer. Check the status at the top, then choose what you want to do below.";
    await loadStatus();
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
loadProviderSettings();

function saveChat() {
  try { localStorage.setItem(chatKey, JSON.stringify(chatMessages.slice(-16))); } catch {}
}

$("#assistant-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("#assistant-input");
  const button = $("#assistant-send");
  const content = input.value.trim();
  if (!content) return;
  chatMessages.push({ role: "user", content });
  chatMessages = chatMessages.slice(-16);
  saveChat();
  renderChat();
  input.value = "";
  button.disabled = true;
  $("#assistant-state").textContent = "THINKING";
  const pending = document.createElement("div");
  pending.className = "assistant-pending";
  pending.textContent = "GUADE is thinking…";
  $("#assistant-messages").append(pending);
  try {
    const result = await request("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: chatMessages }),
    });
    chatMessages.push({ role: "assistant", content: result.answer });
    renderChatActions([...pendingChatActions, ...(result.actions || [])]);
    chatMessages = chatMessages.slice(-16);
    saveChat();
    renderChat();
    $("#assistant-state").textContent = "MAIN PLAYER";
  } catch (error) {
    pending.textContent = error.message;
    pending.classList.add("assistant-error");
    $("#assistant-state").textContent = "MODEL CONNECTION REQUIRED";
  } finally {
    button.disabled = false;
    input.focus();
  }
});

$("#assistant-clear").addEventListener("click", () => {
  chatMessages = [];
  saveChat();
  renderChat();
  $("#assistant-state").textContent = "MAIN PLAYER";
});
document.querySelectorAll("[data-chat-prompt]").forEach((button) => button.addEventListener("click", () => {
  $("#assistant-input").value = button.dataset.chatPrompt;
  $("#assistant-input").focus();
}));
renderChat();

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

async function request(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function formatTime(seconds) {
  if (!seconds) return "--";
  return new Date(seconds * 1000).toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function tickClock() {
  $("#clock").textContent = new Date().toLocaleTimeString([], { hour12: false });
}

async function loadStatus() {
  try {
    const data = await request("/api/status");
    const ready = data.provider === "ready";
    $("#provider-dot").classList.toggle("offline", !ready);
    $("#provider-label").textContent = ready ? `${data.provider_name.toUpperCase()} READY` : data.provider === "offline" ? "OLLAMA OFFLINE" : data.provider === "not_installed" ? "CODEX CLI REQUIRED" : "MODEL KEY REQUIRED";
    $("#model-name").textContent = data.model;
    $("#model-state").textContent = ready ? "Provider available" : data.provider === "offline" ? "Start Ollama to run local workflows" : data.provider === "not_installed" ? "Install Codex CLI for chat" : "Set OPENAI_API_KEY in GUADE's environment";
    $("#storage-path").textContent = data.storage;
  } catch (error) {
    $("#provider-dot").classList.add("offline");
    $("#provider-label").textContent = "LOCAL SERVICE ERROR";
    $("#model-state").textContent = error.message;
  }
}

function renderWorkflowDetail(workflow) {
  state.selectedWorkflow = workflow;
  $("#detail-id").textContent = workflow.id;
  $("#detail-name").textContent = workflow.name;
  $("#detail-description").textContent = workflow.description || "No description provided.";
  $("#detail-agents").textContent = String(workflow.agents).padStart(2, "0");
  $("#detail-steps").textContent = String(workflow.steps).padStart(2, "0");
  $("#detail-sequence").innerHTML = workflow.step_names.map((name, index) => `${index ? '<span class="step-arrow">›</span>' : ""}<span class="step-chip">${escapeHtml(name)}</span>`).join("");
  $("#workflow-select").value = workflow.id;
  document.querySelectorAll(".workflow-row").forEach((row) => row.classList.toggle("selected", row.dataset.workflow === workflow.id));
  renderAgentGrants();
}

function renderAgentGrants() {
  const container = $("#agent-grants");
  const agents = state.selectedWorkflow?.agent_list || [];
  if (!agents.length || !state.connectors.length) {
    container.innerHTML = state.connectors.length ? "" : '<div class="grant-empty">Add a tool server in Connections to grant external tools to workflow agents.</div>';
    return;
  }
  container.innerHTML = `<div class="grant-heading">EXTERNAL TOOL ACCESS <span>choose which agents can use connected servers</span></div>${agents.map((agent) => `
    <div class="agent-grant-row"><span class="agent-grant-name">${escapeHtml(agent.name)}</span><div class="grant-options">${state.connectors.map((connector) => `<label title="${connector.configured ? "" : `Missing environment: ${connector.missing_env.join(", ")}`}" class="grant-option"><input type="checkbox" data-agent-grant="${escapeHtml(agent.id)}" value="${escapeHtml(connector.id)}" ${connector.configured ? "" : "disabled"}><span>${escapeHtml(connector.name)}</span></label>`).join("")}</div></div>`).join("")}`;
}

function renderFinanceConnectors() {
  document.querySelectorAll("[data-finance-category]").forEach((container) => {
    const category = container.dataset.financeCategory;
    const matches = state.connectors.filter((connector) => connector.category === category);
    container.innerHTML = matches.length ? matches.map((connector) => `<div class="finance-connector"><span class="connector-led ${connector.configured ? "" : "needs-setup"}"></span><span>${escapeHtml(connector.name)}</span><small>${connector.configured ? "READY" : "NEEDS SETUP"}</small></div>`).join("") : '<div class="finance-empty">No provider connector configured</div>';
  });
}

function renderWorkflows() {
  $("#workflow-count").textContent = String(state.workflows.length).padStart(2, "0");
  $("#workflow-meta").textContent = `${String(state.workflows.length).padStart(2, "0")} SYSTEMS REGISTERED`;
  $("#workflow-list").innerHTML = state.workflows.length ? state.workflows.map((workflow) => `
    <button class="workflow-row" type="button" data-workflow="${escapeHtml(workflow.id)}">
      <span><span class="workflow-title">${escapeHtml(workflow.name)}</span><span class="workflow-id">${escapeHtml(workflow.id)}</span></span>
      <span class="workflow-description">${escapeHtml(workflow.description)}</span>
      <span class="workflow-count">${workflow.agents} AG / ${workflow.steps} ST</span>
      <span class="workflow-action">INSPECT →</span>
    </button>`).join("") : '<div class="empty-state">No workflow definitions found in examples/.</div>';
  $("#workflow-select").innerHTML = state.workflows.map((workflow) => `<option value="${escapeHtml(workflow.id)}">${escapeHtml(workflow.name)}</option>`).join("");
  document.querySelectorAll(".workflow-row").forEach((row) => row.addEventListener("click", () => {
    const workflow = state.workflows.find((item) => item.id === row.dataset.workflow);
    if (workflow) renderWorkflowDetail(workflow);
  }));
  if (state.workflows.length && !state.selectedWorkflow) renderWorkflowDetail(state.workflows[0]);
  renderLeague();
}

function renderRuns() {
  const active = state.runs.filter((run) => run.status === "running").length;
  const completed = state.runs.filter((run) => run.status === "succeeded").length;
  $("#active-count").textContent = String(active).padStart(2, "0");
  $("#completed-count").textContent = String(completed).padStart(2, "0");
  $("#run-list").innerHTML = state.runs.length ? state.runs.map((run) => `
    <button class="run-row" type="button" data-run="${escapeHtml(run.id)}">
      <span><span class="run-id">${escapeHtml(run.id)}</span><span class="run-workflow">${escapeHtml(run.workflow)}</span></span>
      <span class="run-task">${escapeHtml(run.task)}</span>
      <span class="run-time">${escapeHtml(formatTime(run.created_at))}</span>
      <span class="state state-${escapeHtml(run.status)}">${escapeHtml(run.status)}</span>
    </button>`).join("") : '<div class="empty-state">No runs recorded yet. Launch a workflow to create the first operation.</div>';
  document.querySelectorAll(".run-row").forEach((row) => row.addEventListener("click", () => openRun(row.dataset.run)));
  renderLeague();
}

const leagueMissions = [
  { id: "income_opportunity_scan", code: "SCOUT-01", title: "Find your first opening", detail: "Scout practical income paths for your skills and budget.", kind: "SCOUTING", prompt: "Find and rank realistic income opportunities for me. Treat revenue estimates as uncertain. Include free validation steps before spending." },
  { id: "shop_setup_kit", code: "SHOP-02", title: "Build a shop launch kit", detail: "Prepare a storefront offer, listing copy, and launch checklist.", kind: "COMMERCE", prompt: "Create a practical shop launch kit: product or service offer, listing copy, search terms, FAQ, pricing hypotheses, and an account setup checklist. Mark unknown details as placeholders." },
  { id: "competitor_intelligence", code: "INTEL-03", title: "Map the competition", detail: "Research comparable offers and identify a useful angle.", kind: "RESEARCH", prompt: "Research comparable offers and competitors for a realistic small business opportunity. Separate sourced facts from assumptions and recommend a low-cost validation experiment." },
  { id: "game_preproduction", code: "DESIGN-04", title: "Blueprint a new game", detail: "Create and review the game plan before any code or dialogue.", kind: "PRE-PRODUCTION", prompt: "Create a pre-production blueprint for this game idea. Do not write code, dialogue, or production assets. First capture the audience, platform, core player fantasy, scope, constraints, unknowns, and assumptions. Produce a reviewed design brief with pillars, core loop, key systems, first playable milestone, risks, acceptance criteria, and a human approval gate before production." },
];
const saintOrders = ["saint-scholar", "saint-forger", "saint-seeker", "fallen-oracle", "fallen-judge", "fallen-trickster"];

function renderLeague() {
  if (!$("#arena-missions")) return;
  const workflowsById = new Map(state.workflows.map((item) => [item.id, item]));
  const available = leagueMissions.filter((mission) => workflowsById.has(mission.id));
  $("#arena-missions").innerHTML = available.length ? available.map((mission, index) => `
    <article class="mission-card" data-mission-kind="${mission.kind}"><div class="mission-top"><span>${mission.code}</span><span class="mission-kind">${mission.kind}</span></div><h3>${mission.title}</h3><p>${mission.detail}</p><button type="button" data-deploy-mission="${mission.id}"><span>DEPLOY CREW</span><b>${String(index + 1).padStart(2, "0")} ↗</b></button></article>`).join("") : '<div class="empty-state">No mission workflows are installed yet. Open the Workshop to inspect your available systems.</div>';
  $("#arena-missions").querySelectorAll("[data-deploy-mission]").forEach((button) => button.addEventListener("click", () => deployMission(button.dataset.deployMission)));

  const activeRuns = state.runs.filter((run) => run.status === "running");
  const successes = state.runs.filter((run) => run.status === "succeeded").length;
  const rank = successes >= 25 ? "CHAMPION" : successes >= 10 ? "CAPTAIN" : successes >= 3 ? "OPERATOR" : "ROOKIE";
  const selected = state.selectedWorkflow || state.workflows[0];
  const agents = selected?.agent_list || [];
  $("#league-runs").textContent = String(state.runs.length).padStart(2, "0");
  $("#league-rank").textContent = rank;
  $("#league-agents").textContent = String(agents.length).padStart(2, "0");
  $("#league-agent-note").textContent = selected ? `${selected.name} workflow crew` : "No workflow crew loaded";
  $("#arena-live-state").textContent = activeRuns.length ? `${activeRuns.length} OPERATION${activeRuns.length === 1 ? "" : "S"} ACTIVE` : "STANDING BY";
  $("#master-status").classList.toggle("is-active", activeRuns.length > 0);
  const agentMarkup = agents.slice(0, 6).map((agent, index) => {
    const busy = activeRuns.some((run) => run.workflow === selected.id);
    const order = saintOrders[index];
    const alignment = index < 3 ? "RADIANT ORDER" : "FALLEN ORDER";
    return `<div class="crew-unit ${busy ? "crew-working" : ""}"><span class="crew-avatar ${index < 3 ? "radiant" : "fallen"}"><svg aria-hidden="true"><use href="/saint-icons.svg#${order}"></use></svg></span><span><strong>${escapeHtml(agent.name)}</strong><small>${alignment} · ${busy ? "ON MISSION" : "READY"}</small></span><i></i></div>`;
  }).join("");
  $("#arena-roster").innerHTML = agentMarkup || '<div class="empty-state">Choose a workflow in the Workshop to view its agents.</div>';
  $("#crew-nodes").innerHTML = agents.slice(0, 3).map((agent, index) => `<span class="node-orbit orbit-${index + 1}"><svg aria-hidden="true"><use href="/saint-icons.svg#${saintOrders[index]}"></use></svg></span>`).join("") + `<strong>${agents.length ? `${agents.length} AGENTS` : "NO CREW"}</strong><small>${selected ? escapeHtml(selected.name.toUpperCase()) : "LOAD WORKFLOWS"}</small>`;
  const recent = state.runs.slice(0, 4);
  $("#arena-history").innerHTML = recent.length ? recent.map((run) => `<button class="arena-history-row" type="button" data-arena-run="${escapeHtml(run.id)}"><span class="history-run-dot state-${escapeHtml(run.status)}"></span><strong>${escapeHtml(run.workflow)}</strong><span>${escapeHtml(run.task)}</span><small>${escapeHtml(run.status.toUpperCase())}</small></button>`).join("") : '<div class="empty-state">No deployments yet. Pick a mission to run your first operation.</div>';
  $("#arena-history").querySelectorAll("[data-arena-run]").forEach((row) => row.addEventListener("click", () => { showView("create"); openRun(row.dataset.arenaRun); }));
}

function deployMission(workflowId) {
  const mission = leagueMissions.find((item) => item.id === workflowId);
  const workflow = state.workflows.find((item) => item.id === workflowId);
  if (!mission || !workflow) return;
  renderWorkflowDetail(workflow);
  $("#task-input").value = `${mission.prompt}\n\nMY PROFILE\n${profileBrief()}`;
  $("#arena-live-state").textContent = "DEPLOYING MISSION";
  $("#dispatch-state").textContent = "DISPATCHING FROM LEAGUE";
  $("#run-form").requestSubmit();
}

async function loadRuns() {
  state.runs = await request("/api/runs");
  renderRuns();
  if (state.selectedRun && state.runs.some((run) => run.id === state.selectedRun && run.status === "running")) {
    await loadRunDetails(state.selectedRun);
  }
}

async function loadRunDetails(runId) {
  const run = await request(`/api/runs/${encodeURIComponent(runId)}`);
  const stepHtml = run.steps.map((step) => `
    <article class="step-output"><h3>${escapeHtml(step.step_id)} / ${escapeHtml(step.agent_id)} / ${escapeHtml(step.model)}</h3><pre>${escapeHtml(step.output)}</pre></article>`).join("");
  const artifactHtml = run.artifacts.length ? `<div class="artifact-list"><div class="section-index">GENERATED ARTIFACTS</div>${run.artifacts.map((artifact) => `<div class="artifact-item"><div class="artifact-name">${escapeHtml(artifact.path)} · ${artifact.size} bytes</div>${artifact.text === null ? '<div class="artifact-content">Preview unavailable for this file.</div>' : `<pre class="artifact-content">${escapeHtml(artifact.text)}</pre>`}</div>`).join("")}</div>` : "";
  const failure = run.error ? `<pre class="error-output">${escapeHtml(run.error)}</pre>` : "";
  $("#run-detail-title").textContent = `OPERATION / ${run.id}`;
  $("#run-detail-body").innerHTML = `<div class="run-summary"><span>STATE <strong>${escapeHtml(run.status)}</strong></span><span>WORKFLOW <strong>${escapeHtml(run.workflow)}</strong></span><span>STARTED <strong>${escapeHtml(formatTime(run.created_at))}</strong></span></div><div class="run-summary"><span>TASK</span><strong>${escapeHtml(run.task)}</strong></div>${failure}${stepHtml || (run.status === "running" ? '<div class="empty-state">Agents are working. Step output will appear here as it is recorded.</div>' : '<div class="empty-state">No step output was recorded.</div>')}${artifactHtml}`;
  $("#run-detail").classList.remove("hidden");
}

async function openRun(runId) {
  state.selectedRun = runId;
  try {
    await loadRunDetails(runId);
    $("#run-detail").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    $("#form-message").textContent = error.message;
  }
}

async function refresh() {
  $("#refresh-button").disabled = true;
  try {
    await Promise.all([loadStatus(), loadRuns()]);
  } catch (error) {
    $("#form-message").textContent = error.message;
  } finally {
    $("#refresh-button").disabled = false;
  }
}

async function loadConnectors() {
  const connectors = await request("/api/connectors");
  state.connectors = connectors;
  renderAgentGrants();
  renderFinanceConnectors();
  const list = $("#connector-list");
  if (!connectors.length) {
    list.innerHTML = '<div class="empty-state">No external tool servers connected. Add an MCP server to make its tools available to selected agents.</div>';
    return;
  }
  list.innerHTML = connectors.map((connector) => `
    <article class="connector-row" data-connector="${escapeHtml(connector.id)}">
      <div class="connector-summary"><span class="connector-led ${connector.configured ? "" : "needs-setup"}"></span><div><strong>${escapeHtml(connector.name)}</strong><small>${escapeHtml(connector.id)} · ${escapeHtml(connector.command)}</small></div></div>
      <div class="connector-state">${connector.configured ? "ENVIRONMENT READY" : `NEEDS ${escapeHtml(connector.missing_env.join(", "))}`}</div>
      <div class="connector-actions"><button class="connector-inspect" type="button" ${connector.configured ? "" : "disabled"}>Inspect tools</button><button class="connector-remove" type="button" aria-label="Remove ${escapeHtml(connector.name)}" title="Remove connector">×</button></div>
      <div class="connector-tools" hidden></div>
    </article>`).join("");
  list.querySelectorAll(".connector-inspect").forEach((button) => button.addEventListener("click", async () => {
    const row = button.closest(".connector-row");
    const output = row.querySelector(".connector-tools");
    button.disabled = true;
    output.hidden = false;
    output.textContent = "Starting server and listing tools…";
    try {
      const result = await request(`/api/connectors/${encodeURIComponent(row.dataset.connector)}/inspect`);
      output.innerHTML = result.tools.length ? result.tools.map((tool) => `<div class="tool-entry"><strong>${escapeHtml(tool.name)}</strong><span>${escapeHtml(tool.description)}</span></div>`).join("") : "Server connected; it exposes no tools.";
    } catch (error) {
      output.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }));
  list.querySelectorAll(".connector-remove").forEach((button) => button.addEventListener("click", async () => {
    const row = button.closest(".connector-row");
    if (!window.confirm(`Remove connector ${row.dataset.connector}?`)) return;
    try {
      await request(`/api/connectors/${encodeURIComponent(row.dataset.connector)}`, { method: "DELETE" });
      await loadConnectors();
    } catch (error) {
      $("#connector-message").textContent = error.message;
    }
  }));
}

function renderMcpCatalog() {
  const list = $("#mcp-catalog-list");
  if (!state.catalog.length) {
    list.innerHTML = '<div class="empty-state">No compatible servers found. Try another search.</div>';
    return;
  }
  list.innerHTML = state.catalog.map((server, index) => {
    const transport = server.connection.transport === "http" ? server.connection.url : server.connection.package;
    const existing = state.connectors.find((item) => item.name === server.title || item.id === server.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40));
    return `<article class="catalog-server"><div class="catalog-server-main"><strong>${escapeHtml(server.title)}</strong><small>${escapeHtml(server.name)} · v${escapeHtml(server.version)}</small><p>${escapeHtml(server.description || "No description supplied.")}</p><span class="catalog-transport">${escapeHtml(transport || "No connection method")}</span></div><div class="catalog-server-actions">${server.repository ? `<a href="${escapeHtml(server.repository)}" target="_blank" rel="noopener noreferrer">Source</a>` : ""}<button type="button" data-catalog-index="${index}">${existing ? "Configured" : "Use server"}</button></div></article>`;
  }).join("");
  list.querySelectorAll("[data-catalog-index]").forEach((button) => button.addEventListener("click", () => {
    const server = state.catalog[Number(button.dataset.catalogIndex)];
    if (server) prepareCatalogConnector(server);
  }));
}

async function loadMcpCatalog(query = "") {
  $("#mcp-catalog-state").textContent = "SEARCHING OFFICIAL REGISTRY";
  try {
    const result = await request(`/api/mcp-catalog?search=${encodeURIComponent(query)}`);
    state.catalog = result.servers;
    $("#mcp-catalog-state").textContent = `${result.servers.length} AVAILABLE`;
    renderMcpCatalog();
  } catch (error) {
    $("#mcp-catalog-state").textContent = "REGISTRY UNAVAILABLE";
    $("#mcp-catalog-list").innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  }
}

function prepareCatalogConnector(server) {
  const connection = server.connection;
  const id = server.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "mcp-server";
  $("#connector-id").value = id.length > 1 ? id : `mcp-${id}`;
  $("#connector-name").value = server.title.slice(0, 80);
  $("#connector-category").value = server.category;
  $("#connector-transport").value = connection.transport;
  $("#connector-transport").dispatchEvent(new Event("change"));
  if (connection.transport === "http") {
    $("#connector-url").value = connection.url;
    $("#connector-headers").value = connection.headers.map((header) => `${header.name}=${header.env_name}`).join("\n");
  } else {
    $("#connector-command").value = connection.command[0];
    $("#connector-args").value = connection.args.slice(1).join("\n");
    $("#connector-env").value = "";
  }
  $("#connector-message").textContent = "Review the source, add any required local credentials, then save and inspect. No package has been installed or launched yet.";
  $("#connector-form-panel").scrollIntoView({ behavior: "smooth", block: "center" });
}

let catalogSearchTimer;
$("#mcp-catalog-search").addEventListener("input", () => {
  clearTimeout(catalogSearchTimer);
  catalogSearchTimer = setTimeout(() => loadMcpCatalog($("#mcp-catalog-search").value), 350);
});
loadMcpCatalog();

function renderOpportunities(query = "") {
  const needle = query.trim().toLowerCase();
  const matches = state.opportunities.filter((item) => !needle || `${item.name} ${item.model}`.toLowerCase().includes(needle));
  $("#opportunity-summary").textContent = `${matches.length} of ${state.opportunities.length} platforms · source catalog, not a revenue forecast`;
  const list = $("#opportunity-list");
  list.innerHTML = matches.length ? matches.map((item) => `<article class="opportunity-row"><div><strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(item.model)}</p></div><button type="button" data-plan-opportunity="${escapeHtml(item.name)}">Plan this</button></article>`).join("") : '<div class="empty-state">No matches. Try a broader search.</div>';
  list.querySelectorAll("[data-plan-opportunity]").forEach((button) => button.addEventListener("click", () => {
    const opportunity = state.opportunities.find((item) => item.name === button.dataset.planOpportunity);
    if (!opportunity) return;
    const prompt = `Think through whether ${opportunity.name} is a viable income opportunity for me. Its listed monetization model is: ${opportunity.model}. Compare fit with my skills, audience, weekly hours, and budget shown in the Income desk. Recommend a low-cost validation test, important platform requirements to verify, risks/costs, and a 1-4 step plan. Do not assume earnings or claim current platform terms without checking.`;
    $("#assistant-input").value = prompt;
    $("#assistant-input").focus();
    setAssistantOpen(true);
    $("#assistant-form").requestSubmit();
  }));
}

async function loadOpportunities() {
  try {
    const result = await request("/api/opportunities");
    state.opportunities = result.opportunities;
    renderOpportunities();
  } catch (error) {
    $("#opportunity-summary").textContent = error.message;
  }
}
$("#opportunity-search").addEventListener("input", (event) => renderOpportunities(event.target.value));
loadOpportunities();

function terminalAppend(value) {
  const output = $("#terminal-output");
  const clean = value.replace(/\x1b\][^\x07]*(?:\x07|\x1b\\)/g, "").replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "").replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, "");
  output.textContent = (output.textContent + clean).slice(-200_000);
  output.scrollTop = output.scrollHeight;
}

async function pollTerminal() {
  if (!state.terminalSession) return;
  try {
    const result = await request(`/api/terminal/read?session=${encodeURIComponent(state.terminalSession)}`);
    if (result.output) terminalAppend(result.output);
    if (result.closed) {
      $("#terminal-state").textContent = "SESSION ENDED";
      stopTerminalPolling();
      $("#terminal-input").disabled = true;
      $("#terminal-send").disabled = true;
      $("#terminal-interrupt").disabled = true;
    }
  } catch (error) {
    $("#terminal-state").textContent = error.message;
    stopTerminalPolling();
  }
}

function stopTerminalPolling() {
  if (state.terminalTimer) clearInterval(state.terminalTimer);
  state.terminalTimer = null;
}

function activateTerminal(session, cwd) {
  state.terminalSession = session;
  sessionStorage.setItem("guade-terminal-session", session);
  $("#terminal-cwd").textContent = cwd;
  $("#terminal-state").textContent = "RUNNING";
  $("#terminal-input").disabled = false;
  $("#terminal-send").disabled = false;
  $("#terminal-stop").disabled = false;
  $("#terminal-interrupt").disabled = false;
  $("#terminal-output").textContent = "";
  stopTerminalPolling();
  pollTerminal();
  state.terminalTimer = setInterval(pollTerminal, 350);
  $("#terminal-input").focus();
}

$("#terminal-consent").addEventListener("change", (event) => {
  $("#terminal-start").disabled = !event.currentTarget.checked;
});
$("#terminal-start").addEventListener("click", async () => {
  const button = $("#terminal-start");
  button.disabled = true;
  $("#terminal-state").textContent = "STARTING";
  try {
    const result = await request("/api/terminal/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmed: true }) });
    activateTerminal(result.session, result.cwd);
  } catch (error) {
    $("#terminal-state").textContent = error.message;
    button.disabled = !$("#terminal-consent").checked;
  }
});

$("#terminal-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("#terminal-input");
  const value = input.value;
  if (!value || !state.terminalSession) return;
  input.value = "";
  try {
    await request("/api/terminal/input", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session: state.terminalSession, input: value }) });
  } catch (error) {
    terminalAppend(`\n${error.message}\n`);
  }
});

$("#terminal-interrupt").addEventListener("click", async () => {
  if (!state.terminalSession) return;
  await request("/api/terminal/input", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session: state.terminalSession, input: "\u0003", raw: true }) }).catch((error) => terminalAppend(`\n${error.message}\n`));
});

$("#terminal-stop").addEventListener("click", async () => {
  if (!state.terminalSession) return;
  const id = state.terminalSession;
  stopTerminalPolling();
  await request(`/api/terminal/${encodeURIComponent(id)}`, { method: "DELETE" }).catch(() => {});
  state.terminalSession = null;
  sessionStorage.removeItem("guade-terminal-session");
  $("#terminal-state").textContent = "STOPPED";
  $("#terminal-input").disabled = true;
  $("#terminal-send").disabled = true;
  $("#terminal-stop").disabled = true;
  $("#terminal-interrupt").disabled = true;
  $("#terminal-start").disabled = !$("#terminal-consent").checked;
});

const savedTerminalSession = sessionStorage.getItem("guade-terminal-session");
if (savedTerminalSession) {
  state.terminalSession = savedTerminalSession;
  pollTerminal().then(() => {
    if (state.terminalSession) {
      $("#terminal-cwd").textContent = "Existing local shell session";
      $("#terminal-stop").disabled = false;
      $("#terminal-input").disabled = false;
      $("#terminal-send").disabled = false;
      $("#terminal-interrupt").disabled = false;
      state.terminalTimer = setInterval(pollTerminal, 350);
    }
  });
}

function parseEnvironmentMap(raw) {
  const mapping = {};
  for (const line of raw.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)) {
    const split = line.indexOf("=");
    if (split <= 0) throw new Error("Use one TARGET=LOCAL_VARIABLE mapping per line.");
    mapping[line.slice(0, split).trim()] = line.slice(split + 1).trim();
  }
  return mapping;
}

$("#connector-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = $("#connector-message");
  const command = $("#connector-command").value.trim();
  const transport = $("#connector-transport").value;
  if (transport === "stdio" && !command) return;
  try {
    const httpMode = transport === "http";
    const result = await request("/api/connectors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: $("#connector-id").value.trim(),
        name: $("#connector-name").value.trim(),
        category: $("#connector-category").value,
        transport,
        command: httpMode ? [] : [command],
        args: httpMode ? [] : $("#connector-args").value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
        env: httpMode ? {} : parseEnvironmentMap($("#connector-env").value),
        url: httpMode ? $("#connector-url").value.trim() : "",
        headers: httpMode ? parseEnvironmentMap($("#connector-headers").value) : {},
      }),
    });
    message.textContent = result.configured ? "Connector saved. Inspect its tools, then grant it in a workflow." : `Saved. Set ${result.missing_env.join(", ")} in your terminal and restart GUADE.`;
    event.currentTarget.reset();
    await loadConnectors();
  } catch (error) {
    message.textContent = error.message;
  }
});

$("#connector-transport").addEventListener("change", () => {
  const httpMode = $("#connector-transport").value === "http";
  $("#stdio-fields").hidden = httpMode;
  $("#http-fields").hidden = !httpMode;
  $("#connector-command").required = !httpMode;
  $("#connector-url").required = httpMode;
});

function selectedRadio(name) {
  return document.querySelector(`input[name="${name}"]:checked`)?.value;
}

const profileInputs = ["#profile-skills", "#profile-audience", "#profile-hours", "#profile-budget"];
try {
  const savedProfile = JSON.parse(localStorage.getItem("guade-income-profile") || "{}");
  profileInputs.forEach((selector) => { if (savedProfile[selector]) $(selector).value = savedProfile[selector]; });
} catch {}
profileInputs.forEach((selector) => $(selector).addEventListener("change", () => {
  const profile = Object.fromEntries(profileInputs.map((key) => [key, $(key).value]));
  try { localStorage.setItem("guade-income-profile", JSON.stringify(profile)); } catch {}
}));

function profileBrief() {
  const details = [
    `Skills, experience, and assets: ${$("#profile-skills").value.trim() || "not provided"}`,
    `Audience, location, and channels: ${$("#profile-audience").value.trim() || "not provided"}`,
    `Available time: ${$("#profile-hours").value || "not provided"} hours per week`,
    `Startup budget: ${$("#profile-budget").value.trim() || "not provided"}`,
  ];
  return details.join("\n");
}

const viewTitles = { home: "Operations Arena", opportunities: "Mission Board", create: "Workshop", connections: "Agent Loadout" };
function showView(view, updateUrl = true, scrollTop = true) {
  if (!viewTitles[view]) view = "home";
  document.querySelectorAll("[data-view-page]").forEach((element) => { element.hidden = element.dataset.viewPage !== view; });
  document.querySelectorAll(".nav-item[data-view]").forEach((link) => link.classList.toggle("active", link.dataset.view === view));
  document.querySelector(".breadcrumb strong").textContent = viewTitles[view].toUpperCase();
  document.title = "GUADE | " + viewTitles[view];
  if (updateUrl) {
    const nav = [...document.querySelectorAll(".nav-item[data-view]")].find((link) => link.dataset.view === view);
    if (nav) history.replaceState(null, "", nav.getAttribute("href"));
  }
  if (scrollTop) window.scrollTo({ top: 0, behavior: "smooth" });
}
document.querySelectorAll(".nav-item[data-view]").forEach((link) => link.addEventListener("click", (event) => {
  event.preventDefault();
  showView(link.dataset.view);
}));
const initialHash = location.hash;
const initialNav = [...document.querySelectorAll(".nav-item[data-view]")].find((link) => link.getAttribute("href") === initialHash);
const initialView = initialNav?.dataset.view || ({ "#launcher": "create", "#activity": "create", "#creator": "create", "#payments": "connections" }[initialHash]) || "home";
showView(initialView, false);
$(".brand").addEventListener("click", (event) => { event.preventDefault(); showView("home"); });

document.querySelectorAll("[data-launch-workflow]").forEach((button) => button.addEventListener("click", () => {
  const workflowId = button.dataset.launchWorkflow;
  const platform = button.dataset.platform;
  $("#workflow-select").value = workflowId;
  const workflow = state.workflows.find((item) => item.id === workflowId);
  if (workflow) renderWorkflowDetail(workflow);
  const directive = workflowId === "income_opportunity_scan"
    ? `Find and rank realistic income opportunities for me. Treat all revenue estimates as uncertain and include validation steps before spending.\n\nMY PROFILE\n${profileBrief()}`
    : `Create a practical shop and offer setup kit for ${platform || "the platform I choose"}. Build the profile, listing or service copy, pricing hypotheses, FAQs, and account setup checklist. Clearly mark missing facts as placeholders.\n\nMY PROFILE\n${profileBrief()}`;
  $("#task-input").value = directive;
  showView("create", true, false);
  $("#launcher").scrollIntoView({ behavior: "smooth" });
  $("#task-input").focus({ preventScroll: true });
}));
document.querySelectorAll("[data-scroll-to]").forEach((button) => button.addEventListener("click", () => {
  const target = document.getElementById(button.dataset.scrollTo);
  const view = target.dataset.viewPage || "home";
  showView(view, true, false);
  target.scrollIntoView({ behavior: "smooth" });
}));
document.querySelectorAll("[data-go-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.goView)));
$("#arena-refresh").addEventListener("click", () => refresh());

$("#video-upload").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  const message = $("#media-message");
  if (file.size > 2_000_000_000) {
    message.textContent = "Video must be 2 GB or smaller.";
    return;
  }
  if (state.sourceUrl) URL.revokeObjectURL(state.sourceUrl);
  state.sourceFile = file;
  state.sourceId = null;
  state.sourceUrl = URL.createObjectURL(file);
  const player = $("#source-video");
  player.src = state.sourceUrl;
  player.classList.remove("hidden");
  $("#source-name").textContent = `${file.name} · ${(file.size / 1_000_000).toFixed(1)} MB`;
  message.textContent = "Uploading footage to local GUADE storage…";
  $("#render-clip").disabled = true;
  $("#generate-thumbnail").disabled = true;
  try {
    const result = await request(`/api/media/upload?filename=${encodeURIComponent(file.name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    });
    state.sourceId = result.id;
    state.sourceDuration = result.duration;
    $("#clip-start").max = String(result.duration);
    $("#clip-end").max = String(result.duration);
    $("#clip-end").value = String(Math.min(30, result.duration));
    $("#thumbnail-time").max = String(result.duration);
    $("#thumbnail-time").value = String(Math.min(3, result.duration));
    $("#render-clip").disabled = false;
    $("#generate-thumbnail").disabled = false;
    message.textContent = `Source ready · ${result.duration.toFixed(1)} seconds · saved locally.`;
  } catch (error) {
    message.textContent = error.message;
  }
});

$("#render-clip").addEventListener("click", async () => {
  const button = $("#render-clip");
  const message = $("#media-message");
  button.disabled = true;
  message.textContent = "Rendering clip…";
  try {
    const result = await request("/api/media/clips", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_id: state.sourceId, start: Number($("#clip-start").value), end: Number($("#clip-end").value), aspect: selectedRadio("clip-aspect") }),
    });
    const preview = $("#clip-preview");
    preview.src = result.url;
    preview.classList.remove("hidden");
    $("#clip-placeholder").classList.add("hidden");
    const download = $("#clip-download");
    download.href = result.url;
    download.download = result.filename;
    download.classList.remove("hidden");
    message.textContent = `Rendered ${result.duration}s ${result.aspect} clip · ${(result.size / 1_000_000).toFixed(1)} MB.`;
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

async function createThumbnail() {
  const video = $("#source-video");
  if (!state.sourceId || !video.videoWidth) throw new Error("Load a video before creating a thumbnail.");
  const frameTime = Number($("#thumbnail-time").value);
  if (!Number.isFinite(frameTime) || frameTime < 0 || frameTime > state.sourceDuration) throw new Error("Choose a frame time inside the source video.");
  if (Math.abs(video.currentTime - frameTime) > 0.05) {
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("Timed out seeking to the selected frame.")), 5000);
      video.addEventListener("seeked", () => { clearTimeout(timeout); resolve(); }, { once: true });
      video.currentTime = frameTime;
    });
  }
  const canvas = document.createElement("canvas");
  const isShort = selectedRadio("thumb-aspect") === "short";
  canvas.width = isShort ? 720 : 1280;
  canvas.height = isShort ? 1280 : 720;
  const context = canvas.getContext("2d");
  const scale = Math.max(canvas.width / video.videoWidth, canvas.height / video.videoHeight);
  const drawnWidth = video.videoWidth * scale;
  const drawnHeight = video.videoHeight * scale;
  context.drawImage(video, (canvas.width - drawnWidth) / 2, (canvas.height - drawnHeight) / 2, drawnWidth, drawnHeight);
  const shade = context.createLinearGradient(0, canvas.height * 0.42, 0, canvas.height);
  shade.addColorStop(0, "rgba(2, 8, 4, 0.05)");
  shade.addColorStop(1, "rgba(2, 8, 4, 0.92)");
  context.fillStyle = shade;
  context.fillRect(0, 0, canvas.width, canvas.height);
  const pad = canvas.width * 0.065;
  context.strokeStyle = "rgba(84, 244, 119, 0.92)";
  context.lineWidth = Math.max(2, canvas.width / 500);
  context.strokeRect(pad, pad, canvas.width - pad * 2, canvas.height - pad * 2);
  context.fillStyle = "#a1ffad";
  context.font = `600 ${canvas.width * 0.026}px ui-monospace, monospace`;
  context.fillText("GUADE / CREATOR STUDIO", pad * 1.5, pad * 1.8);
  const headline = $("#thumbnail-title").value.trim() || "YOUR VIDEO TITLE";
  const fontSize = canvas.width * (isShort ? 0.09 : 0.075);
  context.font = `700 ${fontSize}px system-ui, sans-serif`;
  context.textBaseline = "bottom";
  const maxWidth = canvas.width - pad * 3;
  const words = headline.toUpperCase().split(/\s+/);
  const lines = [];
  let line = "";
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word;
    if (line && context.measureText(candidate).width > maxWidth) {
      lines.push(line);
      line = word;
    } else line = candidate;
  }
  if (line) lines.push(line);
  const lineHeight = fontSize * 1.05;
  const visibleLines = lines.slice(-3);
  let y = canvas.height - pad * 1.65;
  for (const text of visibleLines.reverse()) {
    context.lineWidth = Math.max(3, fontSize * 0.1);
    context.strokeStyle = "rgba(0, 0, 0, 0.82)";
    context.strokeText(text, pad * 1.5, y, maxWidth);
    context.fillStyle = "#f5fff6";
    context.fillText(text, pad * 1.5, y, maxWidth);
    y -= lineHeight;
  }
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("Could not render the thumbnail frame.");
  const saved = await request(`/api/media/thumbnails?filename=${encodeURIComponent(headline || "thumbnail")}`, {
    method: "POST",
    headers: { "Content-Type": "image/png" },
    body: blob,
  });
  const result = $("#thumbnail-result");
  result.innerHTML = `<img src="${escapeHtml(saved.url)}" alt="Generated thumbnail"><a href="${escapeHtml(saved.url)}" download="${escapeHtml(saved.filename)}">Download ${escapeHtml(saved.filename)}</a>`;
}

$("#generate-thumbnail").addEventListener("click", async () => {
  const button = $("#generate-thumbnail");
  button.disabled = true;
  $("#media-message").textContent = "Rendering and saving thumbnail…";
  try {
    await createThumbnail();
    $("#media-message").textContent = "Thumbnail saved to local GUADE media storage.";
  } catch (error) {
    $("#media-message").textContent = error.message;
  } finally {
    button.disabled = !state.sourceId;
  }
});

async function loadMediaStatus() {
  try {
    const status = await request("/api/status");
    state.mediaReady = status.media_tools;
    $("#media-state").textContent = status.media_tools ? "FFMPEG READY" : "FFMPEG REQUIRED";
  } catch {
    $("#media-state").textContent = "MEDIA STATUS UNKNOWN";
  }
}

$("#run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#run-button");
  const message = $("#form-message");
  button.disabled = true;
  $("#dispatch-state").textContent = "DISPATCHING";
  message.textContent = "Submitting operation…";
  try {
    const result = await request("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        workflow: $("#workflow-select").value,
        task: $("#task-input").value,
        allow_shell: $("#allow-shell").checked,
        connector_grants: Object.fromEntries([...document.querySelectorAll("[data-agent-grant]:checked")].reduce((map, checkbox) => {
          const agentId = checkbox.dataset.agentGrant;
          map.set(agentId, [...(map.get(agentId) || []), checkbox.value]);
          return map;
        }, new Map())),
      }),
    });
    state.selectedRun = result.run_id;
    message.textContent = `Operation ${result.run_id} started.`;
    $("#dispatch-state").textContent = "RUNNING";
    await loadRuns();
    await openRun(result.run_id);
    clearInterval(state.pollTimer);
    state.pollTimer = setInterval(async () => {
      await loadRuns();
      const current = state.runs.find((run) => run.id === state.selectedRun);
      if (!current || current.status !== "running") {
        clearInterval(state.pollTimer);
        $("#dispatch-state").textContent = current?.status?.toUpperCase() || "STANDING BY";
      }
    }, 1800);
  } catch (error) {
    message.textContent = error.message;
    $("#dispatch-state").textContent = "DISPATCH FAILED";
  } finally {
    button.disabled = false;
  }
});

$("#workflow-select").addEventListener("change", () => {
  const workflow = state.workflows.find((item) => item.id === $("#workflow-select").value);
  if (workflow) renderWorkflowDetail(workflow);
});
$("#choose-workflow").addEventListener("click", () => { showView("create", true, false); $("#launcher").scrollIntoView({ behavior: "smooth" }); });
$("#refresh-button").addEventListener("click", refresh);
$("#close-detail").addEventListener("click", () => $("#run-detail").classList.add("hidden"));
tickClock();
setInterval(tickClock, 1000);
Promise.all([loadStatus(), request("/api/workflows").then((items) => { state.workflows = items; renderWorkflows(); }), loadRuns(), loadConnectors(), loadMediaStatus()]).catch((error) => {
  $("#form-message").textContent = error.message;
});
setInterval(() => loadRuns().catch(() => {}), 5000);
