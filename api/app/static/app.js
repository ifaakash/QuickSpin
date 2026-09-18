// DevOpsHub dashboard. Plain fetch calls against the FastAPI service.

const el = (id) => document.getElementById(id);

const groupSelect = el("group");
const hostSelect = el("host");
const userSelect = el("user");
const runButton = el("run");
const commandBox = el("command");
const commandBadge = el("cmd-badge");
const outputBox = el("output");
const statusBar = el("status");
const elapsedBox = el("elapsed");

// ---------- helpers ----------

async function getJSON(url) {
  const response = await fetch(url);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || `${url} returned ${response.status}`);
  }
  return body;
}

async function postJSON(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  return { ok: response.ok, body };
}

// Replace a dropdown's contents. Each option is { value, text }.
function fillSelect(select, options) {
  select.innerHTML = "";
  for (const option of options) {
    const element = document.createElement("option");
    element.value = option.value;
    element.textContent = option.text;
    select.appendChild(element);
  }
}

// Current form state, in the shape the API expects.
function currentRequest() {
  return {
    group: groupSelect.value,
    host: hostSelect.value,
    user: userSelect.value,
  };
}

function targetLabel() {
  const request = currentRequest();
  return request.host || `${request.group} (all hosts)`;
}

// ---------- navbar ----------

function setConnection(ok, text) {
  el("conn-dot").className = `conn-dot ${ok ? "ok" : "fail"}`;
  el("conn-text").textContent = text;
}

function switchView(name) {
  for (const tab of document.querySelectorAll(".nav-tab")) {
    tab.classList.toggle("is-active", tab.dataset.view === name);
  }
  el("view-run").hidden = name !== "run";
  el("view-inventory").hidden = name !== "inventory";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  el("theme-icon").textContent = theme === "dark" ? "◑" : "◐";
  localStorage.setItem("devopshub-theme", theme);
}

function toggleTheme() {
  const current = document.documentElement.dataset.theme;
  applyTheme(current === "dark" ? "light" : "dark");
}

// ---------- stat tiles ----------

function setStat(id, value, cssClass = "") {
  const node = el(id);
  node.textContent = value;
  node.className = `stat-value ${cssClass}`;
}

// ---------- data loading ----------

async function loadGroups() {
  const data = await getJSON("/api/groups");
  fillSelect(groupSelect, data.groups.map((name) => ({ value: name, text: name })));
  setStat("stat-groups", data.groups.length);
  return data.groups;
}

async function loadHosts(group) {
  const data = await getJSON(`/api/groups/${encodeURIComponent(group)}/hosts`);
  // Empty value means no --limit, so the playbook hits the whole group.
  const options = [{ value: "", text: "All hosts in group" }];
  for (const host of data.hosts) {
    options.push({ value: host.name, text: host.label });
  }
  fillSelect(hostSelect, options);
  setStat("stat-hosts", data.hosts.length);
}

async function loadUsers() {
  const data = await getJSON("/api/users");
  fillSelect(userSelect, data.users.map((name) => ({ value: name, text: name })));
}

// ---------- command panel ----------

// Ask the API what these inputs would produce. The command string is built by
// the same build_command() the runner uses, so the panel cannot drift from
// what actually executes.
async function refreshPreview() {
  if (!groupSelect.value || !userSelect.value) return;

  const { ok, body } = await postJSON("/api/preview", currentRequest());
  commandBadge.textContent = "preview";
  commandBadge.className = "badge";
  commandBox.classList.add("is-stale");
  commandBox.textContent = ok ? body.command_pretty : `# rejected: ${body.detail}`;
}

async function copyCommand() {
  try {
    await navigator.clipboard.writeText(commandBox.textContent);
    el("copy").textContent = "Copied";
    setTimeout(() => (el("copy").textContent = "Copy"), 1200);
  } catch {
    el("copy").textContent = "Press Cmd+C";
    setTimeout(() => (el("copy").textContent = "Copy"), 1600);
  }
}

// ---------- ansible output rendering ----------

// Classify one line of ansible output. The keyword stays visible in the text,
// so the colour is a second signal rather than the only one.
function lineClass(line) {
  if (line.startsWith("PLAY RECAP")) return "ln-play";
  if (line.startsWith("PLAY [")) return "ln-play";
  if (line.startsWith("TASK [") || line.startsWith("RUNNING HANDLER")) return "ln-task";
  if (/^(fatal|failed):/.test(line) || line.includes("UNREACHABLE!") || line.includes("FAILED!")) return "ln-fail";
  if (/^changed:/.test(line)) return "ln-changed";
  if (/^\[WARNING\]/.test(line) || /^\s*\[DEPRECATION/.test(line)) return "ln-warn";
  if (/^ok:/.test(line)) return "ln-ok";
  if (/^(skipping|ignoring):/.test(line)) return "ln-dim";
  if (/^={5,}|^\w+day \d+ \w+ \d{4}/.test(line)) return "ln-dim";
  if (/^-{3} stderr/.test(line)) return "ln-fail";

  // Recap line, e.g. "moo : ok=0 changed=0 unreachable=1 failed=0 ...".
  const recap = line.match(/^\S+\s+:\s+ok=(\d+)/);
  if (recap) {
    const bad = /(unreachable|failed)=([1-9]\d*)/.test(line);
    const changed = /changed=([1-9]\d*)/.test(line);
    if (bad) return "ln-fail";
    return changed ? "ln-changed" : "ln-ok";
  }
  return "";
}

// Build the output block one line at a time. Each line's text is set with
// textContent, so ansible output is never treated as markup.
function renderOutput(text) {
  outputBox.innerHTML = "";
  if (!text.trim()) {
    const empty = document.createElement("span");
    empty.className = "empty";
    empty.textContent = "(no output)";
    outputBox.appendChild(empty);
    return;
  }
  for (const line of text.replace(/\s+$/, "").split("\n")) {
    const span = document.createElement("span");
    span.className = `ln ${lineClass(line)}`.trim();
    span.textContent = line || " ";
    outputBox.appendChild(span);
  }
}

function renderPlain(text, cssClass = "empty") {
  outputBox.innerHTML = "";
  const span = document.createElement("span");
  span.className = cssClass;
  span.textContent = text;
  outputBox.appendChild(span);
}

// ---------- elapsed timer ----------
// The run blocks, so show time moving to prove the page has not frozen.

let elapsedTimer = null;

function startElapsed() {
  const started = Date.now();
  elapsedBox.textContent = "0.0s";
  elapsedTimer = setInterval(() => {
    elapsedBox.textContent = `${((Date.now() - started) / 1000).toFixed(1)}s`;
  }, 100);
}

function stopElapsed(finalText) {
  clearInterval(elapsedTimer);
  elapsedTimer = null;
  elapsedBox.textContent = finalText;
}

// ---------- running ----------

// Status always carries a glyph and a word, so it never rests on colour alone.
function setStatus(glyph, text, cssClass) {
  statusBar.textContent = `${glyph} ${text}`;
  statusBar.className = `status ${cssClass}`;
}

async function runPlaybook() {
  if (runButton.disabled) return;

  const request = currentRequest();
  const target = targetLabel();

  runButton.disabled = true;
  runButton.classList.add("is-busy");
  el("run-label").textContent = "Running";
  setStatus("◌", `Running on ${target}`, "");
  renderPlain("Waiting for ansible to finish...");
  startElapsed();

  try {
    const { ok, body } = await postJSON("/api/run", request);

    if (!ok) {
      stopElapsed("");
      setStatus("✕", `Rejected: ${body.detail}`, "fail");
      renderPlain(body.detail, "ln ln-fail");
      setStat("stat-status", "Rejected", "fail");
      setStat("stat-duration", "—");
      return;
    }

    stopElapsed(`${body.duration}s`);

    // The command panel now shows what actually ran, not a preview.
    commandBox.textContent = body.command_pretty;
    commandBox.classList.remove("is-stale");
    commandBadge.textContent = "executed";
    commandBadge.className = "badge live";

    const glyph = body.ok ? "✓" : "✕";
    const word = body.ok ? "Success" : "Failed";
    const tone = body.ok ? "ok" : "fail";

    setStatus(glyph, `${word}  ·  rc=${body.returncode}  ·  ${target}`, tone);
    setStat("stat-status", `${glyph} ${word}`, tone);
    setStat("stat-duration", `${body.duration}s`);

    let text = body.stdout;
    if (body.stderr) {
      text += `\n--- stderr ---\n${body.stderr}`;
    }
    renderOutput(text);
    outputBox.scrollTop = 0;
  } catch (error) {
    stopElapsed("");
    setStatus("✕", `Request failed: ${error.message}`, "fail");
    renderPlain(error.message, "ln ln-fail");
  } finally {
    runButton.disabled = false;
    runButton.classList.remove("is-busy");
    el("run-label").textContent = "Run playbook";
  }
}

// ---------- inventory view ----------

async function loadInventoryTable(groups) {
  const body = el("inv-body");
  body.innerHTML = "";
  let hostCount = 0;

  for (const group of groups) {
    const data = await getJSON(`/api/groups/${encodeURIComponent(group)}/hosts`);
    for (const host of data.hosts) {
      hostCount += 1;
      // Everything here comes out of the inventory file, so it goes in as
      // text, never as markup.
      const row = document.createElement("tr");
      for (const [value, cssClass] of [[group, ""], [host.name, ""], [host.ip, "mono"]]) {
        const cell = document.createElement("td");
        cell.textContent = value;
        cell.className = cssClass;
        row.appendChild(cell);
      }
      body.appendChild(row);
    }
  }

  el("inv-note").textContent =
    `${groups.length} group${groups.length === 1 ? "" : "s"}, ${hostCount} host${hostCount === 1 ? "" : "s"}`;
}

// ---------- wiring ----------

groupSelect.addEventListener("change", async () => {
  await loadHosts(groupSelect.value);
  refreshPreview();
});
hostSelect.addEventListener("change", refreshPreview);
userSelect.addEventListener("change", refreshPreview);
runButton.addEventListener("click", runPlaybook);
el("copy").addEventListener("click", copyCommand);
el("theme-toggle").addEventListener("click", toggleTheme);

// Cmd+Enter (or Ctrl+Enter) runs, from anywhere on the page.
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    runPlaybook();
  }
});

for (const tab of document.querySelectorAll(".nav-tab")) {
  tab.addEventListener("click", () => switchView(tab.dataset.view));
}

document.addEventListener("DOMContentLoaded", async () => {
  const saved = localStorage.getItem("devopshub-theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved || (prefersDark ? "dark" : "light"));

  try {
    const groups = await loadGroups();
    await loadUsers();
    if (groupSelect.value) {
      await loadHosts(groupSelect.value);
    }
    await loadInventoryTable(groups);
    setConnection(true, "inventory loaded");
    refreshPreview();
  } catch (error) {
    setConnection(false, "inventory error");
    setStatus("✕", `Could not load inventory: ${error.message}`, "fail");
    renderPlain(error.message, "ln ln-fail");
  }
});
