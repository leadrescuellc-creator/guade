// Copyright (c) 2026 LeadRescue LLC. All rights reserved.
const $ = (selector) => document.querySelector(selector);
const state = { workflows: [], runs: [], selectedWorkflow: null, selectedRun: null, pollTimer: null };

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
    $("#provider-label").textContent = ready ? "MODEL LINK READY" : "MODEL KEY REQUIRED";
    $("#model-name").textContent = data.model;
    $("#model-state").textContent = ready ? "Provider credentials detected" : "Set OPENAI_API_KEY in this terminal";
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
      body: JSON.stringify({ workflow: $("#workflow-select").value, task: $("#task-input").value, allow_shell: $("#allow-shell").checked }),
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
Promise.all([loadStatus(), request("/api/workflows").then((items) => { state.workflows = items; renderWorkflows(); }), loadRuns()]).catch((error) => {
  $("#form-message").textContent = error.message;
});
setInterval(() => loadRuns().catch(() => {}), 5000);
