// Mission Control console. Plain JavaScript, no build step.
//
// Safety: report text (especially the engineer's note) is untrusted. Every value
// is inserted with textContent through el(); nothing is ever parsed as HTML.

const FIELDS = ["name", "station", "wind_knots", "temp_c", "fuel_pct", "note"];
const NUMBER_FIELDS = new Set(["wind_knots", "temp_c", "fuel_pct"]);
const READINGS = [
  { key: "wind_knots", label: "Wind", unit: "kn", limit: "≤ 25" },
  { key: "temp_c", label: "Temperature", unit: "°C", limit: "≥ 4" },
  { key: "fuel_pct", label: "Fuel", unit: "%", limit: "98–100" },
];

const state = {
  reports: [],          // rows from /console/reports
  filter: "all",
  query: "",
  selectedId: null,
  tab: "overview",
  detail: null,         // { report, analysis, briefing } for the selected report
};
let refreshTimer = null;

// ===== helpers ==================================================================

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "text") node.textContent = String(value);
    else if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

async function api(path, options = {}) {
  try {
    const response = await fetch(path, { ...options, headers: { "content-type": "application/json" } });
    let body = null;
    try { body = await response.json(); } catch { body = null; }
    return { ok: response.ok, status: response.status, body };
  } catch {
    return { ok: false, status: 0, body: { message: "Cannot reach the server." } };
  }
}

function toast(message, kind = "ok") {
  const node = el("div", { class: `toast ${kind}`, role: "status", text: message });
  document.getElementById("toasts").append(node);
  setTimeout(() => node.remove(), 4000);
}

const money = (value) => (value === null || value === undefined ? "—" : `$${Number(value).toFixed(4)}`);
const verdictText = (v) => (v === "no_go" ? "NO GO" : v === "go" ? "GO" : "—");
const pad = (n) => String(n).padStart(2, "0");

function ago(iso) {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours} h ago` : new Date(iso).toLocaleDateString();
}

function deadline(createdAt, minutes) {
  return new Date(createdAt).getTime() + minutes * 60_000;
}

function countdownText(dueMs) {
  const seconds = Math.round((dueMs - Date.now()) / 1000);
  const abs = Math.abs(seconds);
  const text = abs >= 3600
    ? `${Math.floor(abs / 3600)} h ${pad(Math.floor((abs % 3600) / 60))} min` // long past or far off
    : `${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
  return { text: seconds >= 0 ? text : `−${text}`, overdue: seconds < 0, urgent: seconds >= 0 && seconds < 120 };
}

// ===== header =====================================================================

async function loadHealth() {
  const pill = document.getElementById("model-pill");
  const label = document.getElementById("model-label");
  const { ok, body } = await api("/health");
  if (!ok) { label.textContent = "offline"; pill.className = "pill"; return; }
  const demo = body.llm === "demo";
  label.textContent = demo ? "Demo mode" : body.llm;
  pill.className = demo ? "pill demo" : "pill live";
  pill.title = demo
    ? "No API key is set: model steps return canned replies and cost $0. Add ANTHROPIC_API_KEY to .env to use Claude."
    : `Model steps run on ${body.llm}.`;
}

function tickClock() {
  const now = new Date();
  document.getElementById("clock").textContent =
    `${pad(now.getUTCHours())}:${pad(now.getUTCMinutes())}:${pad(now.getUTCSeconds())} UTC`;
}

function renderStats() {
  const needReview = state.reports.filter((r) => r.needs_review && r.briefing_status !== "approved").length;
  const pending = state.reports.filter((r) => r.briefing_status === "pending").length;
  document.getElementById("stat-review").textContent = needReview;
  document.getElementById("stat-pending").textContent = pending;
  document.getElementById("stat-total").textContent = state.reports.length;
  document.querySelector('.stat[data-filter="review"]').classList.toggle("has-alert", needReview > 0);
}

// ===== report list ===================================================================

function matchesFilter(row) {
  if (state.filter === "review" && !(row.needs_review && row.briefing_status !== "approved")) return false;
  if (state.filter === "pending" && row.briefing_status !== "pending") return false;
  if (state.filter === "approved" && row.briefing_status !== "approved") return false;
  if (!state.query) return true;
  const haystack = `#${row.id} ${row.station} ${row.name} ${row.subsystem || ""}`.toLowerCase();
  return haystack.includes(state.query);
}

async function loadList() {
  const { ok, body } = await api("/console/reports");
  if (!ok) return false;
  state.reports = body;
  renderStats();
  renderList();
  return true;
}

function renderList() {
  const rows = state.reports.filter(matchesFilter);
  document.getElementById("report-list").replaceChildren(...rows.map(renderListItem));
  const empty = document.getElementById("list-empty");
  empty.hidden = rows.length > 0;
  empty.firstElementChild.textContent = state.reports.length ? "No reports match." : "No reports yet. File the first one.";
}

function renderListItem(row) {
  const ready = row.analysis_status === "ready";
  let status;
  if (row.analysis_status === "processing") status = el("span", { class: "tag info" }, [el("span", { class: "spinner" }), "Analysing"]);
  else if (row.analysis_status === "failed") status = el("span", { class: "tag no_go", text: "Pipeline failed" });

  return el("li", {}, el("button", {
    class: `report-item ${ready ? row.verdict : ""}`,
    "aria-current": row.id === state.selectedId ? "true" : null,
    onclick: () => select(row.id),
  }, [
    el("span", { class: "top" }, [
      el("span", { class: "title", text: `#${row.id} · ${row.station}` }),
      el("span", { class: "time", text: ago(row.created_at) }),
    ]),
    el("span", { class: "sub", text: [row.name, row.subsystem].filter(Boolean).join(" · ") }),
    el("span", { class: "tags" }, [
      status,
      ready && el("span", { class: `tag ${row.verdict}`, text: verdictText(row.verdict) }),
      ready && el("span", { class: "tag", text: `${row.effective_severity} · ${row.brief_by_minutes} min` }),
      ready && row.needs_review && row.briefing_status !== "approved" && el("span", { class: "tag warn", text: "Needs review" }),
      row.briefing_status === "approved" && el("span", { class: "tag approved", text: "✓ Briefing approved" }),
      row.briefing_status === "pending" && el("span", { class: "tag", text: "Awaiting approval" }),
    ]),
  ]));
}

function setFilter(filter) {
  state.filter = filter;
  for (const tab of document.querySelectorAll(".segmented button")) {
    tab.setAttribute("aria-selected", String(tab.dataset.filter === filter));
  }
  renderList();
  document.body.dataset.view = "list";
}

// ===== detail ========================================================================

async function select(id, { quiet = false } = {}) {
  state.selectedId = id;
  history.replaceState(null, "", `#report-${id}/${state.tab}`); // a link to this report and tab
  document.body.dataset.view = "detail";
  renderList();
  if (!quiet) renderLoading();

  const [report, analysis, briefing] = await Promise.all([
    api(`/reports/${id}`),
    api(`/reports/${id}/analysis`),
    api(`/reports/${id}/briefing`),
  ]);
  if (state.selectedId !== id) return; // another report was picked while loading
  if (!report.ok) {
    state.detail = null;
    document.getElementById("detail").replaceChildren(emptyState("Report not found", (report.body && report.body.message) || ""));
    return;
  }
  state.detail = { report: report.body, analysis: analysis.ok ? analysis.body : null, briefing: briefing.ok ? briefing.body : null };
  renderDetail();
}

function renderLoading() {
  document.getElementById("detail").replaceChildren(el("div", { class: "detail-inner" }, [
    el("div", { class: "card stack" }, [el("div", { class: "skeleton", style: "width:40%" }), el("div", { class: "skeleton" }), el("div", { class: "skeleton", style: "width:70%" })]),
  ]));
}

function emptyState(title, text) {
  return el("div", { class: "empty" }, [
    el("div", { class: "empty-icon", "aria-hidden": "true", text: "◎" }),
    el("h2", { text: title }),
    el("p", { text }),
    el("button", { class: "btn primary", type: "button", onclick: openDialog, text: "＋ New report" }),
  ]);
}

function renderDetail() {
  const { report, analysis, briefing } = state.detail;
  const ready = analysis && analysis.status === "ready";
  const tabs = ready ? renderTabs(analysis, briefing) : null;

  let body;
  if (!analysis || analysis.status === "processing") body = processingView(report);
  else if (analysis.status === "failed") body = failedView(report, analysis);
  else if (state.tab === "briefing") body = briefingView(report, briefing);
  else if (state.tab === "trace") body = traceView(analysis);
  else body = overviewView(report, analysis, briefing);

  document.getElementById("detail").replaceChildren(el("div", { class: "detail-inner" }, [
    el("button", { class: "btn ghost back", type: "button", onclick: () => { document.body.dataset.view = "list"; }, text: "← All reports" }),
    detailHeader(report, analysis, briefing),
    tabs,
    body,
  ]));
  tickCountdowns();
}

function detailHeader(report, analysis, briefing) {
  const ready = analysis && analysis.status === "ready";
  const approved = briefing && briefing.status === "approved";
  return el("div", { class: "detail-head" }, [
    el("div", { class: "who" }, [
      el("h1", { text: `Report #${report.id} · ${report.station}` }),
      el("p", { class: "meta", text: `Filed by ${report.name} · ${new Date(report.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}` }),
    ]),
    el("div", { class: "head-right" }, [
      ready && !approved && el("div", {
        class: "countdown",
        "data-deadline": deadline(report.created_at, analysis.brief_by_minutes),
        "data-label": `Brief by · ${analysis.brief_by_minutes} min`,
      }, [
        el("span", { class: "label", text: `Brief by · ${analysis.brief_by_minutes} min` }),
        el("span", { class: "value", text: "--:--" }),
      ]),
      ready
        ? el("span", { class: `verdict-pill ${analysis.verdict}`, title: "Set by code from the readings. The note and the models cannot change it.", text: verdictText(analysis.verdict) })
        : el("span", { class: "verdict-pill pending", text: analysis && analysis.status === "failed" ? "No verdict" : "Analysing…" }),
      ready && briefing && !approved && el("button", { class: "btn primary", type: "button", onclick: () => switchTab("briefing", true), text: "Review & approve" }),
      approved && el("span", { class: "tag approved", text: `✓ Briefing approved by ${briefing.approved_by}` }),
    ]),
  ]);
}

function renderTabs(analysis, briefing) {
  const tab = (id, label, extra) => el("button", {
    role: "tab", type: "button", "aria-selected": String(state.tab === id), onclick: () => switchTab(id),
  }, [label, extra]);
  return el("div", { class: "tabs", role: "tablist" }, [
    tab("overview", "Overview", analysis.needs_review && !(briefing && briefing.status === "approved") && el("span", { class: "tag warn", text: "review" })),
    tab("briefing", "Briefing", briefing && el("span", { class: briefing.status === "approved" ? "tag approved" : "tag", text: briefing.status })),
    tab("trace", "Trace & cost", el("span", { class: "count", text: analysis.trace.length })),
  ]);
}

function switchTab(id, focusApproval = false) {
  state.tab = id;
  history.replaceState(null, "", `#report-${state.selectedId}/${id}`);
  renderDetail();
  if (focusApproval) document.querySelector('.approval input[name="approved_by"]')?.focus();
}

function readingsCard(report, violated) {
  return el("div", { class: "readings" }, READINGS.map(({ key, label, unit, limit }) => {
    const bad = violated.includes(key);
    return el("div", { class: bad ? "reading bad" : "reading" }, [
      el("div", { class: "label" }, [el("span", { text: label }), el("span", { text: `limit ${limit}` })]),
      el("div", { class: "value", text: `${report[key]} ${unit}` }),
      violated.length || bad ? el("div", { class: "status", text: bad ? "✕ Outside limit" : "✓ Within limit" }) : null,
    ]);
  }));
}

function noteCard(report) {
  return el("div", { class: "card" }, [
    el("h3", { text: "Engineer's note" }),
    el("p", { class: "note-label", text: "Untrusted text: shown as written, never followed as instructions." }),
    el("blockquote", { class: "note", text: report.note }),
  ]);
}

function processingView(report) {
  return el("div", { class: "stack" }, [
    el("div", { class: "alert" }, [el("span", { class: "spinner" }), el("div", {}, [
      el("strong", { text: "Analysing this report" }),
      el("span", { text: "Sorting, the three note checks, and the draft/review loop are running. This page updates by itself." }),
    ])]),
    el("div", { class: "card" }, [el("h3", { text: "Readings" }), readingsCard(report, [])]),
    noteCard(report),
  ]);
}

function failedView(report, analysis) {
  return el("div", { class: "stack" }, [
    el("div", { class: "alert error" }, el("div", {}, [el("strong", { text: "The pipeline failed" }), el("span", { text: analysis.error })])),
    el("div", { class: "card" }, [el("h3", { text: "Readings" }), readingsCard(report, [])]),
    noteCard(report),
  ]);
}

function overviewView(report, analysis, briefing) {
  const approved = briefing && briefing.status === "approved";
  const violated = analysis.violations.map((v) => v.reading);
  const severity = analysis.effective_severity === analysis.severity
    ? analysis.severity
    : `${analysis.effective_severity} (model said ${analysis.severity})`;

  return el("div", { class: "stack" }, [
    analysis.needs_review && el("div", { class: "alert" }, el("div", {}, [
      el("strong", { text: approved ? `Flagged for review · briefing approved by ${briefing.approved_by}` : "Needs review" }),
      el("ul", {}, analysis.review_reasons.map((reason) => el("li", { text: reason }))),
    ])),
    el("div", { class: "card" }, [
      el("h3", { text: "Readings vs launch limits" }),
      readingsCard(report, violated),
    ]),
    el("div", { class: "card" }, [
      el("h3", { text: "Assessment" }),
      el("dl", { class: "facts" }, [
        fact("Verdict", `${verdictText(analysis.verdict)} · from code`),
        fact("Subsystem", analysis.subsystem),
        fact("Severity", severity),
        fact("Brief by", `${analysis.brief_by_minutes} minutes`),
        fact("Note flags", analysis.flags.length ? analysis.flags.join(", ") : "none"),
        fact("Report cost", money(analysis.total_cost_usd)),
      ]),
      severity !== analysis.severity && el("p", { class: "note-label", style: "margin-top:10px", text: "A limit violation always counts as high severity." }),
    ]),
    noteCard(report),
  ]);
}

function fact(label, value) {
  return el("div", {}, [el("dt", { text: label }), el("dd", { text: value })]);
}

function briefingView(report, briefing) {
  if (!briefing) return el("div", { class: "card" }, el("p", { class: "note-label", text: "No briefing yet." }));
  const approved = briefing.status === "approved";
  return el("div", { class: "card" }, [
    el("h3", { text: approved ? "Approved briefing" : "Draft briefing · awaiting approval" }),
    el("p", { class: "note-label", text: `Drafted in ${briefing.rounds} round${briefing.rounds === 1 ? "" : "s"}; the reviewer model ${briefing.reviewer_accepted ? "accepted" : "did not accept"} it.` }),
    el("div", { class: "briefing-text", text: briefing.text }),
    approved
      ? el("div", { class: "approved-box", style: "margin-top:16px", text: `✓ Briefing approved by ${briefing.approved_by} · ${new Date(briefing.approved_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}` })
      : approveForm(report.id, state.detail.analysis.verdict),
  ]);
}

function approveForm(reportId, verdict) {
  const message = el("p", { class: "form-message", role: "alert" });
  const name = el("input", { name: "approved_by", placeholder: "Your name", "aria-label": "Your name", autocomplete: "name" });
  const button = el("button", { class: "btn success", type: "submit", text: "Approve briefing" });
  return el("form", { class: "approval", novalidate: true, onsubmit: async (event) => {
    event.preventDefault();
    button.disabled = true;
    const { ok, body } = await api(`/reports/${reportId}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved_by: name.value }),
    });
    button.disabled = false;
    if (ok) {
      toast(`Briefing for report #${reportId} approved.`);
      await loadList();
      await select(reportId, { quiet: true });
      return;
    }
    message.textContent = (body && body.message) || "Briefing not approved.";
  } }, [
    name, button, message,
    el("p", { class: "approval-note", text: `Approving confirms this briefing is accurate and has been read. It does not change the verdict (${verdictText(verdict)}). Only a person can approve; the models can draft and review, never approve.` }),
  ]);
}

function traceView(analysis) {
  const tokensIn = analysis.trace.reduce((sum, s) => sum + s.input_tokens, 0);
  const tokensOut = analysis.trace.reduce((sum, s) => sum + s.output_tokens, 0);
  const calls = analysis.trace.filter((s) => s.kind === "model").length;
  const total = (label, value) => el("div", { class: "total" }, [el("div", { class: "label", text: label }), el("div", { class: "value", text: value })]);

  return el("div", { class: "stack" }, [
    el("div", { class: "card" }, [
      el("h3", { text: "Cost of this report" }),
      el("div", { class: "totals" }, [
        total("Total cost", money(analysis.total_cost_usd)),
        total("Model calls", calls),
        total("Tokens in", tokensIn.toLocaleString()),
        total("Tokens out", tokensOut.toLocaleString()),
      ]),
      !analysis.cost_complete && el("p", { class: "note-label", style: "margin-top:10px", text: "Some steps ran on a model with no price; their cost is not included." }),
    ]),
    el("div", { class: "card" }, [
      el("h3", { text: `Trace · ${analysis.trace.length} steps` }),
      el("ol", { class: "trace" }, analysis.trace.map(traceCard)),
    ]),
  ]);
}

function traceCard(step) {
  return el("li", { class: `step ${step.kind}` }, [
    el("span", { class: "num", text: step.seq }),
    el("div", { class: "body" }, [
      el("div", { class: "head" }, [
        el("span", { class: "name", text: step.name }),
        el("span", { class: "tag", text: step.kind === "code" ? "plain code" : step.model || "call failed" }),
      ]),
      el("div", { class: "nums" }, [
        el("span", {}, ["tokens in ", el("b", { text: step.input_tokens })]),
        el("span", {}, ["tokens out ", el("b", { text: step.output_tokens })]),
        el("span", {}, ["cost ", el("b", { text: step.cost_usd === null ? "no price" : `$${Number(step.cost_usd).toFixed(6)}` })]),
      ]),
      el("div", { class: "summary", text: step.summary }),
    ]),
  ]);
}

function tickCountdowns() {
  for (const node of document.querySelectorAll("[data-deadline]")) {
    const { text, overdue, urgent } = countdownText(Number(node.dataset.deadline));
    node.querySelector(".value").textContent = text;
    node.querySelector(".label").textContent = overdue ? "Briefing overdue" : node.dataset.label;
    node.classList.toggle("overdue", overdue);
    node.classList.toggle("urgent", urgent);
  }
}

// ===== filing dialog ===================================================================

function openDialog() {
  const dialog = document.getElementById("report-dialog");
  if (!dialog.open) dialog.showModal();
  dialog.querySelector('input[name="name"]').focus();
}

function closeDialog() {
  document.getElementById("report-dialog").close();
}

function readForm(form) {
  const data = new FormData(form);
  const payload = {};
  for (const field of FIELDS) {
    const raw = String(data.get(field) ?? "");
    // Numbers go as numbers; an empty box goes as null so the server says "must be a number".
    payload[field] = NUMBER_FIELDS.has(field) ? (raw.trim() === "" ? null : Number(raw)) : raw;
  }
  return payload;
}

function showFieldErrors(form, errors) {
  for (const span of form.querySelectorAll(".field-error")) span.textContent = "";
  for (const input of form.querySelectorAll("input, textarea")) input.removeAttribute("aria-invalid");
  for (const { field, message } of errors) {
    const span = form.querySelector(`.field-error[data-for="${field}"]`);
    if (span) span.textContent = message;
    const input = form.elements.namedItem(field);
    if (input) input.setAttribute("aria-invalid", "true");
  }
  const first = form.querySelector('[aria-invalid="true"]');
  if (first) first.focus();
}

async function fileReport(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const message = document.getElementById("form-message");
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  button.textContent = "Filing…";
  message.textContent = "";

  const { ok, status, body } = await api("/reports", { method: "POST", body: JSON.stringify(readForm(form)) });
  button.disabled = false;
  button.textContent = "File report";

  if (ok) {
    showFieldErrors(form, []);
    form.reset();
    closeDialog();
    toast(`Report #${body.id} filed. Analysing…`);
    state.tab = "overview";
    await loadList();
    await select(body.id);
    scheduleRefresh();
    return;
  }
  showFieldErrors(form, (body && body.errors) || []);
  message.textContent = (body && body.message) || `Report not filed (HTTP ${status}).`;
}

// ===== live refresh ======================================================================

function scheduleRefresh() {
  clearTimeout(refreshTimer);
  const busy = state.reports.some((r) => r.analysis_status === "processing");
  refreshTimer = setTimeout(refresh, busy ? 2000 : 15000);
}

async function refresh() {
  const before = state.reports.find((r) => r.id === state.selectedId);
  await loadList();
  const after = state.reports.find((r) => r.id === state.selectedId);
  const changed = before && after &&
    (before.analysis_status !== after.analysis_status || before.briefing_status !== after.briefing_status);
  if (changed) {
    await select(state.selectedId, { quiet: true });
    if (after.analysis_status === "ready") toast(`Report #${after.id} analysed: ${verdictText(after.verdict)}.`);
  }
  scheduleRefresh();
}

// ===== start ================================================================================

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("report-form").addEventListener("submit", fileReport);
  document.getElementById("new-report").addEventListener("click", openDialog);
  for (const node of document.querySelectorAll('[data-action="new-report"]')) node.addEventListener("click", openDialog);
  for (const node of document.querySelectorAll('[data-action="close-dialog"]')) node.addEventListener("click", closeDialog);
  for (const node of document.querySelectorAll("[data-filter]")) node.addEventListener("click", () => setFilter(node.dataset.filter));
  document.getElementById("search").addEventListener("input", (event) => {
    state.query = event.target.value.trim().toLowerCase();
    renderList();
  });

  tickClock();
  setInterval(() => { tickClock(); tickCountdowns(); }, 1000);
  loadHealth();
  await loadList();

  const linked = location.hash.match(/^#report-(\d+)(?:\/(overview|briefing|trace))?$/);
  if (linked) {
    state.tab = linked[2] || "overview";
    select(Number(linked[1]));
  } else if (location.hash === "#new") {
    openDialog();
  }
  scheduleRefresh();
});
