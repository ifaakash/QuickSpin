// DevOpsHub dashboard. Plain fetch calls against the FastAPI service.

const el = (id) => document.getElementById(id);

const groupSelect = el("group");
const hostSelect = el("host");
const userSelect = el("user");
const keySelect = el("key");
const runButton = el("run");
const commandBox = el("command");
const commandBadge = el("cmd-badge");
const outputBox = el("output");
const statusBar = el("status");
const elapsedBox = el("elapsed");

const jitGroup = el("jit-group");
const jitHost = el("jit-host");
const jitUser = el("jit-user");
const jitKey = el("jit-key");
const jitAction = el("jit-action");
const jitUsername = el("jit-username");
const jitPublickey = el("jit-publickey");
const jitRunButton = el("jit-run");

// Which config panel is showing. Decides what ⌘↵ and the preview act on.
let activeTab = "run";

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

// Replace a dropdown's contents. Each option is { value, text, disabled }.
// Disabled options are still listed on purpose: an encrypted key should be
// visible with the reason it cannot be used, not quietly missing.
function fillSelect(select, options) {
  select.innerHTML = "";
  for (const option of options) {
    const element = document.createElement("option");
    element.value = option.value;
    element.textContent = option.text;
    if (option.disabled) element.disabled = true;
    select.appendChild(element);
  }
}

// Current form state, in the shape the API expects.
function currentRequest() {
  return {
    group: groupSelect.value,
    host: hostSelect.value,
    user: userSelect.value,
    private_key: keySelect.value,
  };
}

function currentJitRequest() {
  return {
    group: jitGroup.value,
    host: jitHost.value,
    user: jitUser.value,
    action: jitAction.value,
    username: jitUsername.value.trim(),
    publickey: jitPublickey.value.trim(),
    private_key: jitKey.value,
  };
}

function targetLabel(request) {
  return request.host || `${request.group} (all hosts)`;
}

// ---------- navbar ----------

function setConnection(ok, text) {
  el("conn-dot").className = `conn-dot ${ok ? "ok" : "fail"}`;
  el("conn-text").textContent = text;
}

function switchView(name) {
  activeTab = name;
  for (const tab of document.querySelectorAll(".nav-tab")) {
    tab.classList.toggle("is-active", tab.dataset.view === name);
  }
  // Run and JIT share one layout and swap only the config panel.
  el("layout").hidden = name === "inventory";
  el("config-run").hidden = name !== "run";
  el("config-jit").hidden = name !== "jit";
  el("view-inventory").hidden = name !== "inventory";

  if (name === "run") refreshPreview();
  if (name === "jit") refreshJitPreview();
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

// Each loader takes its target <select>, so the Run and JIT panels share them.

async function loadGroups(select) {
  const data = await getJSON("/api/groups");
  fillSelect(select, data.groups.map((name) => ({ value: name, text: name })));
  setStat("stat-groups", data.groups.length);
  return data.groups;
}

async function loadHosts(select, group) {
  const data = await getJSON(`/api/groups/${encodeURIComponent(group)}/hosts`);
  // Empty value means no --limit, so the playbook hits the whole group.
  const options = [{ value: "", text: "All hosts in group" }];
  for (const host of data.hosts) {
    options.push({ value: host.name, text: host.label });
  }
  fillSelect(select, options);
  setStat("stat-hosts", data.hosts.length);
}

async function loadUsers(select) {
  const data = await getJSON("/api/users");
  fillSelect(select, data.users.map((name) => ({ value: name, text: name })));
}

// Empty value means no --private-key, so ssh keeps its normal behaviour of
// trying the agent and whatever ansible.cfg points at.
//
// The option value is the key's full path, not its filename: keys come from
// several directories now, and two mounts can hold a "homelab" apiece. The
// label carries the directory for the same reason.
async function loadKeys(select, noteId) {
  const data = await getJSON("/api/ssh-keys");
  const options = [{ value: "", text: "Default (ssh-agent / ansible.cfg)" }];
  for (const key of data.keys) {
    const where = `${key.name}  ·  ${key.directory}`;
    options.push({
      value: key.path,
      text: key.encrypted ? `${where}  — encrypted, use ssh-agent` : where,
      disabled: key.encrypted,
    });
  }
  fillSelect(select, options);

  // Name the directories that exist, so an empty dropdown is obviously a
  // missing mount rather than a broken endpoint.
  const present = data.directories.filter((d) => d.exists).map((d) => d.path);
  const usable = data.keys.filter((key) => !key.encrypted).length;
  el(noteId).textContent = data.keys.length
    ? `${usable} of ${data.keys.length} usable · searched ${present.join(", ")}`
    : `no private keys in ${present.join(", ") || "any configured directory"}`;
}

async function loadJitActions(select) {
  const data = await getJSON("/api/jit/actions");
  fillSelect(select, data.actions.map((name) => ({ value: name, text: name })));
}

// ---------- command panel ----------

// Ask the API what these inputs would produce. The command string is built by
// the same build_command() the runner uses, so the panel cannot drift from
// what actually executes.
async function showPreview(url, request) {
  const { ok, body } = await postJSON(url, request);
  commandBadge.textContent = "preview";
  commandBadge.className = "badge";
  commandBox.classList.add("is-stale");
  commandBox.textContent = ok ? body.command_pretty : `# rejected: ${body.detail}`;
}

async function refreshPreview() {
  if (!groupSelect.value || !userSelect.value) return;
  await showPreview("/api/preview", currentRequest());
}

async function refreshJitPreview() {
  if (!jitGroup.value || !jitUser.value || !jitAction.value) return;
  await showPreview("/api/jit/preview", currentJitRequest());
}

// Typing fires a preview per keystroke otherwise, and each one costs an
// ansible-inventory call on the server. Wait for a pause instead.
function debounce(fn, delay = 300) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

const refreshJitPreviewSoon = debounce(refreshJitPreview);

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

// Shared by both run flows: flip the command badge, paint status and output.
function applyRunResult(body, target) {
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
}

async function runPlaybook() {
  if (runButton.disabled) return;

  const request = currentRequest();
  const target = targetLabel(request);

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

    applyRunResult(body, target);
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

// Revoke deletes the account and its home directory, so make it deliberate.
function confirmRevoke(request, target) {
  return window.confirm(
    `Revoke ${request.username} on ${target}?\n\n` +
    "This deletes the account and its home directory on the target host. " +
    "There is no undo."
  );
}

async function runJit() {
  if (jitRunButton.disabled) return;

  const request = currentJitRequest();
  const target = targetLabel(request);

  if (request.action === "revoke" && !confirmRevoke(request, target)) return;

  jitRunButton.disabled = true;
  jitRunButton.classList.add("is-busy");
  el("jit-run-label").textContent = "Running";
  setStatus("◌", `${request.action} ${request.username} on ${target}`, "");
  renderPlain("Waiting for ansible to finish...");
  startElapsed();

  try {
    const { ok, body } = await postJSON("/api/jit/run", request);

    if (!ok) {
      stopElapsed("");
      setStatus("✕", `Rejected: ${body.detail}`, "fail");
      renderPlain(body.detail, "ln ln-fail");
      setStat("stat-status", "Rejected", "fail");
      setStat("stat-duration", "—");
      return;
    }

    applyRunResult(body, target);
  } catch (error) {
    stopElapsed("");
    setStatus("✕", `Request failed: ${error.message}`, "fail");
    renderPlain(error.message, "ln ln-fail");
  } finally {
    jitRunButton.disabled = false;
    jitRunButton.classList.remove("is-busy");
    el("jit-run-label").textContent = "Run playbook";
  }
}

// The key field only matters for provision — revoke.yml never reads it.
function syncJitAction() {
  const revoking = jitAction.value === "revoke";
  el("jit-key-field").hidden = revoking;
  el("jit-warn").hidden = !revoking;
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
  await loadHosts(hostSelect, groupSelect.value);
  refreshPreview();
});
hostSelect.addEventListener("change", refreshPreview);
userSelect.addEventListener("change", refreshPreview);
keySelect.addEventListener("change", refreshPreview);
runButton.addEventListener("click", runPlaybook);

jitGroup.addEventListener("change", async () => {
  await loadHosts(jitHost, jitGroup.value);
  refreshJitPreview();
});
jitHost.addEventListener("change", refreshJitPreview);
jitUser.addEventListener("change", refreshJitPreview);
jitKey.addEventListener("change", refreshJitPreview);
jitAction.addEventListener("change", () => {
  syncJitAction();
  refreshJitPreview();
});
// Text fields are debounced; the selects above fire immediately.
jitUsername.addEventListener("input", refreshJitPreviewSoon);
jitPublickey.addEventListener("input", refreshJitPreviewSoon);
jitRunButton.addEventListener("click", runJit);
el("copy").addEventListener("click", copyCommand);
el("theme-toggle").addEventListener("click", toggleTheme);

// Cmd+Enter (or Ctrl+Enter) runs, from anywhere on the page.
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    if (activeTab === "jit") runJit();
    else if (activeTab === "run") runPlaybook();
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
    const groups = await loadGroups(groupSelect);
    await loadGroups(jitGroup);
    await loadUsers(userSelect);
    await loadUsers(jitUser);
    await loadKeys(keySelect, "key-note");
    await loadKeys(jitKey, "jit-key-note");
    await loadJitActions(jitAction);
    if (groupSelect.value) {
      await loadHosts(hostSelect, groupSelect.value);
      await loadHosts(jitHost, jitGroup.value);
    }
    syncJitAction();
    await loadInventoryTable(groups);
    setConnection(true, "inventory loaded");
    refreshPreview();
  } catch (error) {
    setConnection(false, "inventory error");
    setStatus("✕", `Could not load inventory: ${error.message}`, "fail");
    renderPlain(error.message, "ln ln-fail");
  }
});
