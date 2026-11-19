// ─── State ────────────────────────────────────────────────────
let currentSource   = "folder";
let resolvedDataPath = "";
let currentRunId    = "";
let pollInterval    = null;
let auditData       = [];
let auditPage       = 1;
const PAGE_SIZE     = 50;
let lastLogCount    = 0;

// ─── Source tab switching ─────────────────────────────────────
function switchTab(tab) {
  currentSource = tab;
  document.getElementById("panel-folder").style.display = tab === "folder" ? "" : "none";
  document.getElementById("panel-zip").style.display    = tab === "zip"    ? "" : "none";
  document.getElementById("tab-folder").classList.toggle("active", tab === "folder");
  document.getElementById("tab-zip").classList.toggle("active",    tab === "zip");

  resolvedDataPath = "";
  hide("folder-preview"); hide("folder-error");
  hide("zip-preview");    hide("zip-error");
  setReady(false);
}

// ─── Result tab switching ─────────────────────────────────────
function switchResultTab(name) {
  const names = ["overview","quality","audit","similarity","recs"];
  names.forEach(t => {
    const el = document.getElementById("rtab-" + t);
    if (el) el.style.display = t === name ? "" : "none";
  });
  document.querySelectorAll(".tab-nav-btn").forEach((btn, i) => {
    btn.classList.toggle("active", names[i] === name);
  });
}

// ─── Utility ──────────────────────────────────────────────────
function hide(id) { const e = document.getElementById(id); if (e) e.style.display = "none"; }
function show(id) { const e = document.getElementById(id); if (e) e.style.display = ""; }
function set(id, v){ const e = document.getElementById(id); if (e) e.textContent = v; }

function setReady(ready) {
  const btn  = document.getElementById("analyze-btn");
  const hint = document.getElementById("analyze-hint");
  btn.disabled = !ready;
  hint.textContent = ready ? "" : "Select or upload a dataset to begin";
}

function setStepperState(step) {
  // step: 1, 2, or 3
  [1, 2, 3].forEach(n => {
    const el = document.getElementById("stepper-" + n);
    if (!el) return;
    el.classList.remove("active", "done");
    if (n < step)       el.classList.add("done");
    else if (n === step) el.classList.add("active");
  });
}

// ─── Folder mode ──────────────────────────────────────────────
function onFolderModeChange() {
  const mode = document.querySelector('input[name="folder-mode"]:checked').value;
  const row  = document.getElementById("custom-path-row");
  row.style.display = mode === "custom" ? "" : "none";
  resolvedDataPath  = "";
  hide("folder-preview"); hide("folder-error");
  setReady(false);
  if (mode === "default") previewFolder("data");
}

function previewFolder(pathOverride) {
  const path = pathOverride || (document.getElementById("folder-path").value || "").trim();
  if (!path) return;

  fetch("/api/classes?path=" + encodeURIComponent(path))
    .then(r => r.json())
    .then(data => {
      hide("folder-error");
      if (!data.classes || !data.classes.length) {
        showErr("folder-error", data.error || "No class sub-folders found in that directory.");
        setReady(false);
        return;
      }
      resolvedDataPath = data.path;
      showInfo("folder-preview",
        `<strong>Path:</strong> ${esc(data.path)}<br/>` +
        `<strong>Classes found (${data.classes.length}):</strong> ${data.classes.map(esc).join(", ")}`
      );
      setReady(true);
    })
    .catch(() => { showErr("folder-error", "Could not reach the server."); setReady(false); });
}

// ─── ZIP upload ───────────────────────────────────────────────
function onDrop(evt) {
  evt.preventDefault();
  const file = evt.dataTransfer.files[0];
  if (file) uploadZip(file);
}

function uploadZip(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".zip")) {
    showErr("zip-error", "Only .zip files are accepted."); return;
  }
  hide("zip-error"); hide("zip-preview");
  show("upload-status");
  document.getElementById("upload-status").querySelector("#upload-status-text") &&
    (document.getElementById("upload-status-text").textContent = `Uploading "${file.name}"…`);

  const form = new FormData();
  form.append("file", file);

  fetch("/api/upload", { method: "POST", body: form })
    .then(r => r.json())
    .then(data => {
      hide("upload-status");
      if (data.error) { showErr("zip-error", data.error); return; }
      resolvedDataPath = data.data_path;
      showInfo("zip-preview",
        `<strong>File uploaded successfully.</strong><br/>` +
        `<strong>Classes found (${data.classes.length}):</strong> ${data.classes.map(esc).join(", ")}`
      );
      setReady(true);
    })
    .catch(() => { hide("upload-status"); showErr("zip-error", "Upload failed. Is the server running?"); });
}

// ─── Info / Error boxes ───────────────────────────────────────
function showInfo(id, html) {
  const el = document.getElementById(id);
  el.innerHTML = html;
  el.style.display = "";
}

function showErr(id, msg) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.style.display = "";
}

// ─── Start analysis ───────────────────────────────────────────
function startAnalysis() {
  if (!resolvedDataPath) return;
  const runSim = document.getElementById("run-similarity").checked;

  hide("source-section");
  hide("results-section");
  show("progress-section");
  setStepperState(2);

  // Reset pipeline steps
  ["validating","processing","similarity","reports"].forEach(s => {
    const el = document.getElementById("pstep-" + s);
    if (el) el.className = "pipeline-step";
  });
  document.getElementById("log-output").textContent = "";
  lastLogCount = 0;

  fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data_path: resolvedDataPath, run_similarity: runSim })
  })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        alert("Error: " + data.error);
        backToSource(); return;
      }
      currentRunId = data.run_id;
      pollInterval = setInterval(pollStatus, 1200);
    })
    .catch(() => { alert("Could not start analysis. Is the server running?"); backToSource(); });
}

// ─── Polling ──────────────────────────────────────────────────
function pollStatus() {
  if (!currentRunId) return;
  fetch("/api/status/" + currentRunId)
    .then(r => r.json())
    .then(data => {
      updateLogs(data.logs || []);
      updatePipelineSteps(data.logs || []);
      if (data.status === "done") {
        clearInterval(pollInterval);
        markDone("reports");
        loadResults();
      } else if (data.status === "error") {
        clearInterval(pollInterval);
        alert("Pipeline error:\n" + (data.error || "Unknown error"));
        newAnalysis();
      }
    })
    .catch(() => {});
}

function updateLogs(logs) {
  if (logs.length === lastLogCount) return;
  lastLogCount = logs.length;
  const box = document.getElementById("log-output");
  box.textContent = logs.join("\n");
  box.scrollTop   = box.scrollHeight;
  set("log-count", `${logs.length} lines`);
}

function updatePipelineSteps(logs) {
  const text = logs.join("\n").toLowerCase();
  if (text.includes("processing class:"))                    markActive("validating");
  if (text.includes("valid:"))                               { markDone("validating"); markActive("processing"); }
  if (text.includes("starting similarity"))                  { markDone("processing"); markActive("similarity"); }
  if (text.includes("similarity analysis skipped") ||
      text.includes("similarity analysis completed") ||
      text.includes("not installed"))                        { markDone("similarity"); markActive("reports"); }
  if (text.includes("generating charts"))                    { markDone("similarity"); markActive("reports"); }
  if (text.includes("pipeline completed"))                   markDone("reports");
}

function markActive(name) {
  const el = document.getElementById("pstep-" + name);
  if (el && !el.classList.contains("done")) el.className = "pipeline-step active";
}

function markDone(name) {
  const el = document.getElementById("pstep-" + name);
  if (el) el.className = "pipeline-step done";
}

// ─── Results ──────────────────────────────────────────────────
function loadResults() {
  fetch("/api/results/" + currentRunId)
    .then(r => r.json())
    .then(data => {
      hide("progress-section");
      show("results-section");
      setStepperState(3);
      renderResults(data);
    })
    .catch(() => { alert("Failed to load results."); newAnalysis(); });
}

function renderResults(data) {
  const ev = data.evaluation || {};

  // Metric cards
  set("m-valid",      ev.total_valid        ?? "—");
  set("m-invalid",    ev.total_invalid       ?? "—");
  set("m-duplicates", ev.total_duplicates    ?? "—");
  set("m-quality",    ev.total_quality_flags ?? "—");
  set("m-processed",  ev.total_processed     ?? "—");
  set("m-similar",    (data.similarity_analysis || {}).similar_pairs ?? "—");

  // Status badge
  const badge   = document.getElementById("dataset-status-badge");
  const status  = ev.dataset_status || "";
  badge.textContent = status;
  badge.className = "status-badge " +
    (status.includes("No major") ? "ok" : status.includes("Review") ? "warn" : "error");

  set("results-subtitle", `${ev.total_valid || 0} valid images across ${Object.keys(ev.class_counts || {}).length} classes`);

  // ── Overview: class table
  const cc = ev.class_counts || {};
  let cHtml = `<table class="data-table" style="max-width:420px;"><thead>
    <tr><th>Class</th><th>Valid Images</th></tr></thead><tbody>`;
  Object.entries(cc).forEach(([cls, cnt]) => {
    cHtml += `<tr><td>${esc(cls)}</td><td>${cnt}</td></tr>`;
  });
  cHtml += "</tbody></table>";
  document.getElementById("class-table-wrap").innerHTML = cHtml;

  renderCharts("charts-overview", ["class_distribution","class_share","image_audit_status"], data.charts || []);

  // ── Quality: issue table
  const qi = ev.quality_issues || {};
  const qtbody = document.getElementById("quality-tbody");
  qtbody.innerHTML = "";
  Object.entries(qi).forEach(([issue, cnt]) => {
    qtbody.innerHTML += `<tr><td>${esc(issue)}</td><td>${cnt}</td></tr>`;
  });

  renderCharts("charts-quality",
    ["image_quality","brightness_distribution","sharpness_distribution","width_distribution","height_distribution"],
    data.charts || []
  );

  // ── Audit table
  auditData = data.image_records || [];
  auditPage = 1;
  const classFilter = document.getElementById("audit-filter-class");
  classFilter.innerHTML = '<option value="">All classes</option>';
  [...new Set(auditData.map(r => r.class))].sort().forEach(c => {
    classFilter.innerHTML += `<option value="${esc(c)}">${esc(c)}</option>`;
  });
  renderAuditTable();

  // ── Similarity
  const sim = data.similarity_analysis || {};
  let simHtml = `<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px;">
    <div style="padding:12px 16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;font-size:.875rem;">
      <strong style="display:block;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:#94a3b8;margin-bottom:2px;">Status</strong>
      ${esc(sim.status || "—")}
    </div>
    <div style="padding:12px 16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;font-size:.875rem;">
      <strong style="display:block;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:#94a3b8;margin-bottom:2px;">Message</strong>
      ${esc(sim.message || "—")}
    </div>
  </div>`;

  if (sim.pairs && sim.pairs.length) {
    simHtml += `<h4 style="margin-bottom:10px;font-size:.875rem;color:#374151;">${sim.pairs.length} similar pair(s) detected above threshold</h4>`;
    sim.pairs.forEach(p => {
      simHtml += `<div class="sim-pair">
        <strong>${esc(p.image_1)}</strong>
        <span style="color:#94a3b8;">↔</span>
        <strong>${esc(p.image_2)}</strong>
        <span class="sim-score">score: ${p.similarity}</span>
      </div>`;
    });
  } else if (sim.status === "completed") {
    simHtml += `<p style="color:#16a34a;font-size:.875rem;">✓ No similar image pairs found above the threshold.</p>`;
  }

  document.getElementById("similarity-content").innerHTML = simHtml;

  // ── Recommendations
  const recs = ev.recommendations || [];
  let recsHtml = recs.map(r =>
    `<div class="rec-item"><span class="rec-arrow">→</span><span>${esc(r)}</span></div>`
  ).join("");

  recsHtml += `<div class="balance-info">
    <div class="balance-chip">
      <strong>Class Balance</strong>${esc(ev.class_balance || "—")}
    </div>
    <div class="balance-chip">
      <strong>Balance Ratio</strong>${ev.class_balance_ratio ?? "—"}
    </div>
    <div class="balance-chip">
      <strong>Unsupported Files</strong>${ev.total_unsupported ?? "—"}
    </div>
  </div>`;

  document.getElementById("recs-content").innerHTML = recsHtml;

  switchResultTab("overview");
}

// ─── Charts ───────────────────────────────────────────────────
function renderCharts(containerId, wanted, available) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  wanted.forEach(name => {
    if (!available.includes(name)) return;
    const img  = document.createElement("img");
    img.src    = `/api/chart/${currentRunId}/${name}`;
    img.alt    = name.replace(/_/g, " ");
    img.title  = name.replace(/_/g, " ");
    img.onerror = () => img.style.display = "none";
    container.appendChild(img);
  });
}

// ─── Audit table rendering ────────────────────────────────────
function renderAuditTable() {
  auditPage = 1;
  renderAuditPage();
}

function renderAuditPage() {
  const search  = (document.getElementById("audit-search").value || "").toLowerCase();
  const stFilt  = document.getElementById("audit-filter-status").value;
  const clFilt  = document.getElementById("audit-filter-class").value;

  const filtered = auditData.filter(r => {
    if (stFilt && r.status !== stFilt)  return false;
    if (clFilt && r.class  !== clFilt)  return false;
    if (search) {
      const hay = `${r.filename} ${r.class} ${r.status} ${r.issues || ""}`.toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });

  set("audit-count", `${filtered.length} record${filtered.length !== 1 ? "s" : ""}`);

  const start = (auditPage - 1) * PAGE_SIZE;
  const page  = filtered.slice(start, start + PAGE_SIZE);
  const tbody = document.getElementById("audit-tbody");
  tbody.innerHTML = "";

  page.forEach(r => {
    const sc = "status-" + (r.status || "").toLowerCase();
    tbody.innerHTML += `<tr>
      <td>${esc(r.class)}</td>
      <td style="font-family:monospace;font-size:.8rem;">${esc(r.filename)}</td>
      <td class="${sc}">${esc(r.status)}</td>
      <td>${r.width  || "—"}</td>
      <td>${r.height || "—"}</td>
      <td>${r.brightness !== "" && r.brightness !== undefined ? r.brightness : "—"}</td>
      <td>${r.sharpness  !== "" && r.sharpness  !== undefined ? r.sharpness  : "—"}</td>
      <td style="font-size:.8rem;color:#ef4444;">${esc(r.issues || "")}</td>
      <td style="text-align:center;">${r.processed ? "✓" : "—"}</td>
    </tr>`;
  });

  // Pagination
  const total = Math.ceil(filtered.length / PAGE_SIZE);
  const pag   = document.getElementById("audit-pagination");
  pag.innerHTML = "";
  for (let i = 1; i <= total; i++) {
    const btn = document.createElement("button");
    btn.textContent = i;
    if (i === auditPage) btn.classList.add("current");
    btn.onclick = () => { auditPage = i; renderAuditPage(); };
    pag.appendChild(btn);
  }
}

// ─── Cancel / Reset ───────────────────────────────────────────
function cancelRun() {
  clearInterval(pollInterval);
  currentRunId = "";
  lastLogCount = 0;
  backToSource();
}

function newAnalysis() {
  clearInterval(pollInterval);
  currentRunId = "";
  lastLogCount = 0;
  resolvedDataPath = "";
  auditData = [];

  const zi = document.getElementById("zip-input");
  if (zi) zi.value = "";
  hide("upload-status"); hide("zip-preview"); hide("zip-error");
  hide("folder-preview"); hide("folder-error");
  setReady(false);
  backToSource();
}

function backToSource() {
  hide("progress-section");
  hide("results-section");
  show("source-section");
  setStepperState(1);
  document.getElementById("mode-default").checked = true;
  onFolderModeChange();
}

// ─── Escape HTML ──────────────────────────────────────────────
function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ─── Init ─────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("folder-path")
    ?.addEventListener("keydown", e => { if (e.key === "Enter") previewFolder(); });

  // Wire up upload-status text span
  const us = document.getElementById("upload-status");
  if (us && !us.querySelector("#upload-status-text")) {
    us.innerHTML = `<div class="upload-status-inner"><span class="spinner"></span><span id="upload-status-text">Uploading…</span></div>`;
  }

  setStepperState(1);
  onFolderModeChange(); // auto-preview data/ folder
});
