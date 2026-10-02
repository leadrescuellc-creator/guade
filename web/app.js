// Copyright (c) 2026 LeadRescue LLC. All rights reserved.
const $ = (selector) => document.querySelector(selector);
const state = { workflows: [], runs: [], connectors: [], selectedWorkflow: null, selectedRun: null, pollTimer: null, sourceFile: null, sourceId: null, sourceDuration: 0, sourceUrl: null, mediaReady: false };

const chatKey = "guade-assistant-chat";
let chatMessages = [];
try {
  const stored = JSON.parse(localStorage.getItem(chatKey) || "[]");
  if (Array.isArray(stored)) chatMessages = stored.filter((item) => ["user", "assistant"].includes(item?.role) && typeof item.content === "string").slice(-16);
} catch {}

function renderChat() {
  const container = $("#assistant-messages");
  if (!chatMessages.length) {
    container.innerHTML = '<div class="assistant-welcome"><span class="assistant-mark">G</span><div><strong>GUADE Assistant</strong><p>Ask me about getting set up, connecting tools, picking a workflow, or a command you are unsure about.</p></div></div>';
    return;
  }
  container.innerHTML = chatMessages.map((message) => `<article class="chat-message ${message.role === "user" ? "chat-user" : "chat-agent"}"><span class="chat-speaker">${message.role === "user" ? "YOU" : "GUADE ASSISTANT"}</span><div class="chat-content"></div></article>`).join("");
  container.querySelectorAll(".chat-content").forEach((node, index) => { node.textContent = chatMessages[index].content; });
  container.scrollTop = container.scrollHeight;
}

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
  } catch (error) {
    $("#provider-message").textContent = error.message;
  }
}

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
    chatMessages = chatMessages.slice(-16);
    saveChat();
    renderChat();
    $("#assistant-state").textContent = "OPERATOR GUIDE";
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
  $("#assistant-state").textContent = "OPERATOR GUIDE";
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
  $("#launcher").scrollIntoView({ behavior: "smooth" });
  $("#task-input").focus({ preventScroll: true });
}));
document.querySelectorAll("[data-scroll-to]").forEach((button) => button.addEventListener("click", () => {
  $(`#${button.dataset.scrollTo}`).scrollIntoView({ behavior: "smooth" });
}));

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
$("#choose-workflow").addEventListener("click", () => $("#launcher").scrollIntoView({ behavior: "smooth" }));
$("#refresh-button").addEventListener("click", refresh);
$("#close-detail").addEventListener("click", () => $("#run-detail").classList.add("hidden"));
document.querySelectorAll(".nav-item").forEach((link) => link.addEventListener("click", () => {
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
  link.classList.add("active");
}));

tickClock();
setInterval(tickClock, 1000);
Promise.all([loadStatus(), request("/api/workflows").then((items) => { state.workflows = items; renderWorkflows(); }), loadRuns(), loadConnectors(), loadMediaStatus()]).catch((error) => {
  $("#form-message").textContent = error.message;
});
setInterval(() => loadRuns().catch(() => {}), 5000);
