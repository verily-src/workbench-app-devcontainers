/* =============================================
   GCP Data Chat — Frontend Logic
   ============================================= */

// --- State ---
let currentStep = 1;
let dataLoaded = false;
let keyLoaded = false;

// --- Initialization ---
document.addEventListener("DOMContentLoaded", () => {
  // Configure marked for markdown rendering
  if (typeof marked !== "undefined") {
    marked.setOptions({
      breaks: true,
      gfm: true,
      highlight: function (code, lang) {
        if (typeof hljs !== "undefined" && lang && hljs.getLanguage(lang)) {
          return hljs.highlight(code, { language: lang }).value;
        }
        return code;
      },
    });
  }
  fetchStatus();
});

// --- API Helpers ---
async function api(url, options = {}) {
  try {
    const resp = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.error || `HTTP ${resp.status}`);
    }
    return data;
  } catch (err) {
    throw err;
  }
}

// --- Status ---
async function fetchStatus() {
  try {
    const s = await api("/api/status");
    // Auto-fill project
    if (s.default_project) {
      const el = document.getElementById("gcpProject");
      if (el && !el.value) {
        el.value = s.default_project;
        document.getElementById("projectHint").textContent =
          "Auto-detected from Workbench credentials";
      }
      const bqEl = document.getElementById("bqProject");
      if (bqEl && !bqEl.value) bqEl.value = s.default_project;
    }
    // Update status indicators
    keyLoaded = s.has_key;
    dataLoaded = s.has_data;
    updateStatusBar();
    updateStepNav();
    if (s.has_data) {
      document.getElementById("btnToChat").disabled = false;
    }
  } catch {
    setStatus("error", "Cannot reach server");
  }
}

function setStatus(state, text) {
  const dot = document.getElementById("statusDot");
  const txt = document.getElementById("statusText");
  dot.className = "status-dot " + state;
  txt.textContent = text;
}

function updateStatusBar() {
  if (dataLoaded && keyLoaded) {
    setStatus("ready", "Ready — data loaded, API key set");
  } else if (keyLoaded) {
    setStatus("warning", "API key set — load data to start chatting");
  } else if (dataLoaded) {
    setStatus("warning", "Data loaded — set API key to chat");
  } else {
    setStatus("warning", "Configure project and API key to begin");
  }
}

// --- Step Navigation ---
function goToStep(step) {
  // Hide all panels
  document.querySelectorAll(".step-panel").forEach((p) => (p.style.display = "none"));
  // Show target
  document.getElementById("step" + step).style.display = "block";
  currentStep = step;
  updateStepNav();

  // Update chat model label when entering chat
  if (step === 3) {
    const model = document.getElementById("modelName").value || "gpt-4o-mini";
    document.getElementById("chatModelLabel").textContent = model;
  }
}

function updateStepNav() {
  document.querySelectorAll(".step-item").forEach((item) => {
    const s = parseInt(item.dataset.step);
    item.classList.remove("active", "completed");
    if (s === currentStep) {
      item.classList.add("active");
    } else if (s < currentStep) {
      item.classList.add("completed");
    }
    // Mark step 1 completed if key is set
    if (s === 1 && keyLoaded && currentStep > 1) item.classList.add("completed");
    // Mark step 2 completed if data loaded
    if (s === 2 && dataLoaded && currentStep > 2) item.classList.add("completed");
  });

  // Update connectors
  const connectors = document.querySelectorAll(".step-connector");
  connectors.forEach((c, i) => {
    c.classList.toggle("done", i + 1 < currentStep);
  });
}

// --- Step 1: Project & Key ---
async function setProject() {
  const project = document.getElementById("gcpProject").value.trim();
  if (!project) {
    showFeedback("projectFeedback", "Please enter a project ID", "error");
    return;
  }
  try {
    await api("/api/set-project", {
      method: "POST",
      body: JSON.stringify({ project }),
    });
    showFeedback("projectFeedback", "Project set: " + project, "success");
    // Also set BQ project
    document.getElementById("bqProject").value = project;
  } catch (err) {
    showFeedback("projectFeedback", err.message, "error");
  }
}

function switchKeyTab(tab) {
  document.getElementById("keyTabSecret").style.display = tab === "secret" ? "block" : "none";
  document.getElementById("keyTabPaste").style.display = tab === "paste" ? "block" : "none";
  document.querySelectorAll(".tab-btn").forEach((btn, i) => {
    btn.classList.toggle("active", (i === 0 && tab === "secret") || (i === 1 && tab === "paste"));
  });
}

async function fetchKey() {
  const project = document.getElementById("smProject").value.trim();
  const secret = document.getElementById("smSecret").value.trim();
  const version = document.getElementById("smVersion").value.trim() || "latest";
  if (!project || !secret) {
    showFeedback("keyFeedback", "Enter project and secret name", "error");
    return;
  }
  showLoading("Loading API key from Secret Manager...");
  try {
    const res = await api("/api/fetch-key", {
      method: "POST",
      body: JSON.stringify({ project, secret_name: secret, version }),
    });
    keyLoaded = true;
    showFeedback("keyFeedback", "API key loaded successfully from Secret Manager", "success");
    updateStatusBar();
  } catch (err) {
    showFeedback("keyFeedback", "Failed: " + err.message, "error");
  } finally {
    hideLoading();
  }
}

async function pasteKey() {
  const key = document.getElementById("pasteKey").value.trim();
  if (!key) {
    showFeedback("keyFeedback", "Please paste your API key", "error");
    return;
  }
  try {
    await api("/api/set-key", {
      method: "POST",
      body: JSON.stringify({ key }),
    });
    keyLoaded = true;
    showFeedback("keyFeedback", "API key saved", "success");
    updateStatusBar();
  } catch (err) {
    showFeedback("keyFeedback", err.message, "error");
  }
}

// --- Step 2: Data Source ---
function switchSource(src) {
  document.getElementById("panelGCS").style.display = src === "gcs" ? "block" : "none";
  document.getElementById("panelBQ").style.display = src === "bigquery" ? "block" : "none";
  document.getElementById("btnGCS").classList.toggle("active", src === "gcs");
  document.getElementById("btnBQ").classList.toggle("active", src === "bigquery");
}

async function discoverBuckets() {
  const project = document.getElementById("gcpProject").value.trim();
  showLoading("Discovering GCS buckets...");
  try {
    const res = await api("/api/discover/buckets?project=" + encodeURIComponent(project));
    const sel = document.getElementById("gcsBucket");
    sel.innerHTML = '<option value="">-- Select a bucket --</option>';
    res.buckets.forEach((b) => {
      const opt = document.createElement("option");
      opt.value = b;
      opt.textContent = b;
      sel.appendChild(opt);
    });
    showFeedback("loadFeedback", `Found ${res.buckets.length} bucket(s)`, "success");
  } catch (err) {
    showFeedback("loadFeedback", "Error discovering buckets: " + err.message, "error");
  } finally {
    hideLoading();
  }
}

async function onBucketChange() {
  const bucket = document.getElementById("gcsBucket").value;
  if (bucket) discoverBlobs();
}

async function discoverBlobs() {
  const bucket = document.getElementById("gcsBucket").value;
  const prefix = document.getElementById("gcsPrefix").value.trim();
  if (!bucket) {
    showFeedback("loadFeedback", "Select a bucket first", "error");
    return;
  }
  showLoading("Browsing files...");
  try {
    const res = await api(
      "/api/discover/blobs?bucket=" +
        encodeURIComponent(bucket) +
        "&prefix=" +
        encodeURIComponent(prefix)
    );
    const sel = document.getElementById("gcsBlob");
    sel.innerHTML = '<option value="">-- Select a file --</option>';
    res.blobs.forEach((b) => {
      const opt = document.createElement("option");
      opt.value = b;
      opt.textContent = b;
      sel.appendChild(opt);
    });
    showFeedback("loadFeedback", `Found ${res.blobs.length} file(s)`, "info");
  } catch (err) {
    showFeedback("loadFeedback", "Error: " + err.message, "error");
  } finally {
    hideLoading();
  }
}

async function discoverDatasets() {
  const project =
    document.getElementById("bqProject").value.trim() ||
    document.getElementById("gcpProject").value.trim();
  if (!project) {
    showFeedback("loadFeedback", "Enter a project ID first", "error");
    return;
  }
  showLoading("Discovering BigQuery datasets...");
  try {
    const res = await api("/api/discover/datasets?project=" + encodeURIComponent(project));
    const sel = document.getElementById("bqDataset");
    sel.innerHTML = '<option value="">-- Select a dataset --</option>';
    res.datasets.forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d;
      opt.textContent = d;
      sel.appendChild(opt);
    });
    showFeedback("loadFeedback", `Found ${res.datasets.length} dataset(s)`, "success");
  } catch (err) {
    showFeedback("loadFeedback", "Error: " + err.message, "error");
  } finally {
    hideLoading();
  }
}

async function onDatasetChange() {
  const ds = document.getElementById("bqDataset").value;
  if (ds) discoverTables();
}

async function discoverTables() {
  const project =
    document.getElementById("bqProject").value.trim() ||
    document.getElementById("gcpProject").value.trim();
  const dataset = document.getElementById("bqDataset").value;
  if (!project || !dataset) {
    showFeedback("loadFeedback", "Select project and dataset first", "error");
    return;
  }
  showLoading("Discovering tables...");
  try {
    const res = await api(
      "/api/discover/tables?project=" +
        encodeURIComponent(project) +
        "&dataset=" +
        encodeURIComponent(dataset)
    );
    const sel = document.getElementById("bqTable");
    sel.innerHTML = '<option value="">-- Select a table --</option>';
    res.tables.forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      sel.appendChild(opt);
    });
    showFeedback("loadFeedback", `Found ${res.tables.length} table(s)`, "info");
  } catch (err) {
    showFeedback("loadFeedback", "Error: " + err.message, "error");
  } finally {
    hideLoading();
  }
}

async function loadGCS() {
  const bucket = document.getElementById("gcsBucket").value;
  const path = document.getElementById("gcsBlob").value;
  const format = document.getElementById("gcsFormat").value;
  if (!bucket || !path) {
    showFeedback("loadFeedback", "Select a bucket and file", "error");
    return;
  }
  showLoading("Loading data from GCS...");
  try {
    const res = await api("/api/load", {
      method: "POST",
      body: JSON.stringify({ source_type: "gcs", bucket, path, format }),
    });
    dataLoaded = true;
    showFeedback(
      "loadFeedback",
      `Loaded ${res.rows.toLocaleString()} rows x ${res.cols} columns from gs://${bucket}/${path}`,
      "success"
    );
    renderPreview(res);
    document.getElementById("btnToChat").disabled = false;
    updateStatusBar();
    updateStepNav();
  } catch (err) {
    showFeedback("loadFeedback", "Load failed: " + err.message, "error");
  } finally {
    hideLoading();
  }
}

async function loadBQ() {
  const project =
    document.getElementById("bqProject").value.trim() ||
    document.getElementById("gcpProject").value.trim();
  const dataset = document.getElementById("bqDataset").value;
  const table = document.getElementById("bqTable").value;
  const limit = parseInt(document.getElementById("bqLimit").value) || 50000;
  if (!project || !dataset || !table) {
    showFeedback("loadFeedback", "Select project, dataset, and table", "error");
    return;
  }
  showLoading("Loading data from BigQuery...");
  try {
    const res = await api("/api/load", {
      method: "POST",
      body: JSON.stringify({ source_type: "bigquery", project, dataset, table, limit }),
    });
    dataLoaded = true;
    showFeedback(
      "loadFeedback",
      `Loaded ${res.rows.toLocaleString()} rows x ${res.cols} columns from ${project}.${dataset}.${table}`,
      "success"
    );
    renderPreview(res);
    document.getElementById("btnToChat").disabled = false;
    updateStatusBar();
    updateStepNav();
  } catch (err) {
    showFeedback("loadFeedback", "Load failed: " + err.message, "error");
  } finally {
    hideLoading();
  }
}

function renderPreview(res) {
  const card = document.getElementById("previewCard");
  card.style.display = "block";

  const badge = document.getElementById("previewBadge");
  badge.textContent = `${res.rows.toLocaleString()} rows x ${res.cols} columns`;
  badge.className = "badge success";

  const head = document.getElementById("previewHead");
  const body = document.getElementById("previewBody");

  // Header row
  head.innerHTML =
    "<tr>" + res.columns.map((c) => `<th>${esc(c)}<br><span style="font-weight:400;font-size:0.75rem;color:#9AA0A6;">${esc(res.dtypes[c] || "")}</span></th>`).join("") + "</tr>";

  // Data rows (first 50 for performance)
  const rows = res.preview.slice(0, 50);
  body.innerHTML = rows
    .map(
      (row) =>
        "<tr>" +
        res.columns.map((c) => `<td title="${esc(String(row[c] ?? ""))}">${esc(String(row[c] ?? ""))}</td>`).join("") +
        "</tr>"
    )
    .join("");

  // Update chat source info
  document.getElementById("chatSourceInfo").textContent =
    `Data loaded: ${res.source_info} (${res.rows.toLocaleString()} rows). Ask questions in plain language.`;
}

// --- Step 3: Chat ---
function askSuggestion(el) {
  document.getElementById("chatInput").value = el.textContent;
  sendMessage();
}

function handleChatKey(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 120) + "px";
}

async function sendMessage() {
  const input = document.getElementById("chatInput");
  const question = input.value.trim();
  if (!question) return;

  // Clear welcome message
  const welcome = document.querySelector(".chat-welcome");
  if (welcome) welcome.remove();

  // Add user message
  appendMessage("user", question);
  input.value = "";
  input.style.height = "auto";

  // Disable send button
  const btn = document.getElementById("btnSend");
  btn.disabled = true;

  // Show typing indicator
  const typingEl = appendTyping();

  const model = document.getElementById("modelName").value || "gpt-4o-mini";
  const useUs = document.getElementById("useUsEndpoint").checked;

  try {
    const res = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        question,
        model,
        use_us_endpoint: useUs,
      }),
    });

    typingEl.remove();
    appendMessage("assistant", res.text, res.chart);
  } catch (err) {
    typingEl.remove();
    appendMessage("assistant", "**Error:** " + err.message);
  } finally {
    btn.disabled = false;
    input.focus();
  }
}

function appendMessage(role, text, chartBase64 = null) {
  const container = document.getElementById("chatMessages");
  const msg = document.createElement("div");
  msg.className = "chat-msg " + role;

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.textContent = role === "user" ? "You" : "AI";

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";

  if (role === "user") {
    bubble.textContent = text;
  } else {
    // Render markdown for assistant
    if (typeof marked !== "undefined") {
      bubble.innerHTML = marked.parse(text || "");
    } else {
      bubble.textContent = text;
    }
    // Highlight code blocks
    bubble.querySelectorAll("pre code").forEach((block) => {
      if (typeof hljs !== "undefined") hljs.highlightElement(block);
    });
  }

  // Add chart image if present
  if (chartBase64) {
    const chartDiv = document.createElement("div");
    chartDiv.className = "msg-chart";
    const img = document.createElement("img");
    img.src = "data:image/png;base64," + chartBase64;
    img.alt = "Generated chart";
    chartDiv.appendChild(img);
    bubble.appendChild(chartDiv);
  }

  msg.appendChild(avatar);
  msg.appendChild(bubble);
  container.appendChild(msg);
  container.scrollTop = container.scrollHeight;
}

function appendTyping() {
  const container = document.getElementById("chatMessages");
  const msg = document.createElement("div");
  msg.className = "chat-msg assistant";
  msg.id = "typingMsg";

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.textContent = "AI";

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.innerHTML = `
    <div class="typing-indicator">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
    </div>`;

  msg.appendChild(avatar);
  msg.appendChild(bubble);
  container.appendChild(msg);
  container.scrollTop = container.scrollHeight;
  return msg;
}

async function clearChat() {
  try {
    await api("/api/chat/clear", { method: "POST" });
  } catch {}
  const container = document.getElementById("chatMessages");
  container.innerHTML = `
    <div class="chat-welcome">
      <div class="welcome-icon">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" stroke="#4285F4" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </div>
      <h3>Chat cleared. Ask a new question!</h3>
      <div class="suggestion-chips">
        <button class="chip" onclick="askSuggestion(this)">What columns are in this table?</button>
        <button class="chip" onclick="askSuggestion(this)">Show me a summary of the data</button>
        <button class="chip" onclick="askSuggestion(this)">Show me a histogram of all numeric columns</button>
      </div>
    </div>`;
}

// --- Utilities ---
function showFeedback(id, msg, type) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = msg;
    el.className = "feedback " + type;
  }
}

function showLoading(text) {
  document.getElementById("loadingText").textContent = text || "Loading...";
  document.getElementById("loadingOverlay").style.display = "flex";
}

function hideLoading() {
  document.getElementById("loadingOverlay").style.display = "none";
}

function esc(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
