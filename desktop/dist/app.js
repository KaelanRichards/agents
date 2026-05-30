// Agents desktop frontend — dependency-free, uses the global window.__TAURI__ API.
// All backend access goes through Rust commands (agentd_get / agentd_action), so the token
// stays in Rust/Keychain and there is no CORS surface.

const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

// ---- backend helpers ------------------------------------------------------

const api = (path) => invoke("agentd_get", { path });
const action = (name, args = {}) =>
	invoke("agentd_action", { action: name, args });
const readDoc = (rel) => invoke("read_doc", { rel });
const writeDoc = (rel, content) => invoke("write_doc", { rel, content });
const listMemory = () => invoke("list_memory");

// ---- tiny DOM utils -------------------------------------------------------

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) =>
	String(s ?? "").replace(
		/[&<>"]/g,
		(c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c],
	);
const pill = (s) => `<span class="pill ${esc(s)}">${esc(s)}</span>`;
const short = (s, n = 8) => esc(String(s ?? "").slice(0, n));
const ts = (s) =>
	esc(
		String(s ?? "")
			.replace("T", " ")
			.slice(0, 19),
	);

let toastTimer;
function toast(msg, isErr = false) {
	const t = $("#toast");
	t.textContent = msg;
	t.className = "toast show" + (isErr ? " err" : "");
	clearTimeout(toastTimer);
	toastTimer = setTimeout(() => (t.className = "toast"), 3200);
}

async function run(fn) {
	try {
		return await fn();
	} catch (e) {
		toast(String(e), true);
		throw e;
	}
}

// ---- loading-state helpers ----

// Run an async action with a button shown in its busy state (spinner, input blocked).
async function busy(btn, fn) {
	if (!btn) return run(fn);
	const wasDisabled = btn.disabled;
	btn.classList.add("busy");
	btn.disabled = true;
	try {
		return await run(fn);
	} finally {
		btn.classList.remove("busy");
		btn.disabled = wasDisabled;
	}
}

// Panel-shaped skeleton shown while a panel's data is in flight (replaces "Loading…").
function skeleton(name) {
	const rows = (n) =>
		Array.from({ length: n }, () => `<div class="skel skel-row"></div>`).join(
			"",
		);
	const cards = (n) =>
		Array.from(
			{ length: n },
			() => `<div class="card skel skel-card"></div>`,
		).join("");
	const head = (t) =>
		`<h1>${t}</h1><p class="sub skel skel-line" style="width:38%"></p>`;
	if (name === "fleet")
		return `${head("Fleet")}<div class="cards">${cards(3)}</div>${rows(4)}`;
	if (name === "config")
		return `${head("Config")}<div class="cards">${cards(2)}</div>${rows(6)}`;
	const title = name.charAt(0).toUpperCase() + name.slice(1);
	return `${head(title)}${rows(7)}`;
}

// ---- panel registry -------------------------------------------------------

let current = "fleet";
const content = () => $("#content");

const panels = {
	fleet: renderFleet,
	runs: renderRuns,
	approvals: renderApprovals,
	queue: renderQueue,
	config: renderConfig,
	memory: renderMemory,
};

async function select(name) {
	current = name;
	document
		.querySelectorAll(".nav")
		.forEach((b) => b.classList.toggle("active", b.dataset.panel === name));
	content().innerHTML = skeleton(name);
	try {
		await panels[name]();
	} catch (e) {
		content().innerHTML = `<div class="empty">Couldn't load: ${esc(e)}<br/><br/>Is agentd running? <button class="btn" id="start-agentd">Start local agentd</button></div>`;
		const b = $("#start-agentd");
		if (b)
			b.onclick = () =>
				run(() => invoke("start_local_agentd")).then(() =>
					toast("Starting agentd…"),
				);
	}
}

function refreshCurrent() {
	if (!current) return;
	const c = content();
	c.classList.add("refreshing");
	Promise.resolve(panels[current]?.()).finally(() =>
		c.classList.remove("refreshing"),
	);
}

// ---- Fleet ----------------------------------------------------------------

async function renderFleet() {
	const f = await api("/api/fleet");
	const servers = f.servers || [];
	const rows = servers.length
		? servers
				.map(
					(s) => `<tr>
            <td class="mono">${esc(s.name)}</td>
            <td>${esc(s.type)}</td>
            <td>${pill(s.status)}</td>
            <td class="mono">${esc(s.ip)}</td>
            <td>€${(s.price_eur || 0).toFixed(2)}/mo</td>
            <td><button class="btn" data-reboot="${esc(s.name)}">Reboot</button></td>
          </tr>`,
				)
				.join("")
		: `<tr><td colspan="6" class="empty">No VMs (set HCLOUD_TOKEN where agentd runs).</td></tr>`;

	content().innerHTML = `
    <h1>Fleet</h1>
    <p class="sub">Machines, cost, and control-plane health.</p>
    <div class="cards">
      <div class="card"><div class="label">Monthly cost</div><div class="kpi">€${(f.monthly_eur || 0).toFixed(2)}</div></div>
      <div class="card"><div class="label">Servers</div><div class="kpi">${servers.length}</div></div>
      <div class="card"><div class="label">Ledger chain</div><div class="kpi small">${f.ledger_ok ? "✓ ok" : "⚠ BROKEN"} <span class="label">(${f.ledger_checked} checked)</span></div></div>
    </div>
    <div class="card"><div class="label">Doctor</div><div class="mono" id="doctor-line" style="margin-top:6px"><span class="spinner"></span>checking…</div></div>
    <div class="row" style="margin:14px 0">
      <button class="btn primary" id="btn-sync">Sync config</button>
      <button class="btn" id="btn-doctor">Run doctor</button>
    </div>
    <table>
      <thead><tr><th>Name</th><th>Type</th><th>Status</th><th>IP</th><th>Cost</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;

	api("/api/doctor")
		.then((d) => {
			const el = $("#doctor-line");
			if (el) el.textContent = d.doctor;
		})
		.catch(() => {
			const el = $("#doctor-line");
			if (el) el.textContent = "(doctor unavailable)";
		});
	$("#btn-sync").onclick = (e) =>
		busy(e.currentTarget, () => action("sync")).then((r) =>
			toast(r.ok ? "Synced" : "Sync failed", !r.ok),
		);
	$("#btn-doctor").onclick = (e) =>
		busy(e.currentTarget, () => action("doctor")).then((r) =>
			toast(r.ok ? "Doctor ok" : "Doctor reported issues", !r.ok),
		);
	content()
		.querySelectorAll("[data-reboot]")
		.forEach((b) => {
			b.onclick = (e) => {
				if (confirm(`Reboot ${b.dataset.reboot}?`))
					busy(e.currentTarget, () =>
						action("reboot", { id: b.dataset.reboot }),
					).then(() => toast("Reboot requested"));
			};
		});
}

// ---- Runs (live ledger) ---------------------------------------------------

async function renderRuns() {
	const entries = await api("/api/ledger?limit=80");
	entries.reverse(); // newest first
	const body = entries.length
		? entries
				.map(
					(e) => `<tr>
            <td>${ts(e.ts)}</td>
            <td>${esc(e.kind)}</td>
            <td>${pill(e.status)}</td>
            <td>${esc(e.profile || "")}</td>
            <td>${esc(e.agent || "")}</td>
            <td>${esc(String(e.prompt || "").slice(0, 90))}</td>
          </tr>`,
				)
				.join("")
		: `<tr><td colspan="6" class="empty">No runs recorded yet.</td></tr>`;

	content().innerHTML = `
    <h1>Runs</h1>
    <p class="sub">Live, append-only ledger — every queue / approval / broker / eval transition. Updates in real time.</p>
    <table>
      <thead><tr><th>When</th><th>Kind</th><th>Status</th><th>Profile</th><th>Agent</th><th>Summary</th></tr></thead>
      <tbody>${body}</tbody>
    </table>`;
}

// ---- Approvals ------------------------------------------------------------

async function renderApprovals() {
	const rows = await api("/api/approvals?status=pending&limit=100");
	updateApprovalBadge(rows.length);
	const body = rows.length
		? rows
				.map(
					(r) => `<tr>
            <td>${ts(r.created_at)}</td>
            <td>${esc(r.kind)}</td>
            <td>${esc(r.summary)}</td>
            <td class="row">
              <button class="btn ok" data-approve="${esc(r.id)}">Approve</button>
              <button class="btn err" data-reject="${esc(r.id)}">Reject</button>
            </td>
          </tr>`,
				)
				.join("")
		: `<tr><td colspan="4" class="empty">Inbox clear — no pending approvals.</td></tr>`;

	content().innerHTML = `
    <h1>Approvals</h1>
    <p class="sub">Human-in-the-loop inbox. Risky / outward-facing actions wait here.</p>
    <table>
      <thead><tr><th>When</th><th>Kind</th><th>Summary</th><th>Decision</th></tr></thead>
      <tbody>${body}</tbody>
    </table>`;

	const decide = (id, verb, btn) =>
		busy(btn, () => action(verb, { id })).then(() => {
			toast(verb === "approve" ? "Approved" : "Rejected");
			renderApprovals();
		});
	content()
		.querySelectorAll("[data-approve]")
		.forEach(
			(b) =>
				(b.onclick = (e) =>
					decide(b.dataset.approve, "approve", e.currentTarget)),
		);
	content()
		.querySelectorAll("[data-reject]")
		.forEach(
			(b) =>
				(b.onclick = (e) =>
					decide(b.dataset.reject, "reject", e.currentTarget)),
		);
}

function updateApprovalBadge(n) {
	const badge = $("#badge-approvals");
	if (!badge) return;
	badge.textContent = n;
	badge.hidden = !n;
}

// ---- Queue + Swarm --------------------------------------------------------

async function renderQueue() {
	const [rows, profiles] = await Promise.all([
		api("/api/queue?limit=80"),
		api("/api/profiles"),
	]);
	const body = rows.length
		? rows
				.map(
					(r) => `<tr>
            <td>${ts(r.created_at)}</td>
            <td>${pill(r.status)}</td>
            <td>${esc(r.profile)}</td>
            <td>${esc(r.agent)}</td>
            <td title="${esc(r.task)}">${esc(String(r.task).slice(0, 70))}</td>
            <td class="row">
              <button class="btn" data-log="${esc(r.id)}">Log</button>
              ${r.status === "queued" ? `<button class="btn ok" data-start="${esc(r.id)}">Start</button>` : ""}
              ${r.status === "running" || r.status === "queued" ? `<button class="btn err" data-cancel="${esc(r.id)}">Cancel</button>` : ""}
              ${r.status === "failed" || r.status === "canceled" ? `<button class="btn" data-retry="${esc(r.id)}">Retry</button>` : ""}
            </td>
          </tr>`,
				)
				.join("")
		: `<tr><td colspan="6" class="empty">Queue is empty.</td></tr>`;

	const profOpts = profiles
		.map(
			(p) =>
				`<option value="${esc(p.name)}">${esc(p.name)} (${esc(p.risk)})</option>`,
		)
		.join("");

	content().innerHTML = `
    <h1>Queue</h1>
    <p class="sub">Durable background tasks, each in its own jj workspace. This is the orchestration surface — review a task's workspace with <span class="mono">jj -R &lt;workspace&gt; log</span>, then merge the good ones.</p>
    <div class="card">
      <div class="label">Enqueue a task</div>
      <div class="row" style="margin-top:10px; align-items:flex-end">
        <div class="field"><label>Repo</label><input id="q-repo" placeholder="~/code/myrepo" size="22" /></div>
        <div class="field"><label>Profile</label><select id="q-profile">${profOpts}</select></div>
        <div class="field"><label>Agent</label><select id="q-agent"><option>claude</option><option>codex</option><option>noop</option></select></div>
        <div class="field" style="flex:1"><label>Task</label><input id="q-task" placeholder="what should the agent do?" style="width:100%" /></div>
        <button class="btn primary" id="q-add">Enqueue</button>
      </div>
    </div>
    <table>
      <thead><tr><th>When</th><th>Status</th><th>Profile</th><th>Agent</th><th>Task</th><th>Actions</th></tr></thead>
      <tbody>${body}</tbody>
    </table>
    <div id="q-log"></div>`;

	$("#q-add").onclick = (e) => {
		const args = {
			repo: $("#q-repo").value.trim(),
			profile: $("#q-profile").value,
			agent: $("#q-agent").value,
			task: $("#q-task").value.trim(),
		};
		if (!args.repo || !args.task)
			return toast("Repo and task are required", true);
		busy(e.currentTarget, () => action("queue_add", args)).then((r) => {
			toast(
				r.ok ? "Enqueued" : "Enqueue failed: " + (r.output || r.error || ""),
				!r.ok,
			);
			if (r.ok) renderQueue();
		});
	};

	const act = (id, verb, label, btn) =>
		busy(btn, () => action(verb, { id })).then((r) => {
			toast(r.ok ? label : r.output || r.error || "failed", !r.ok);
			renderQueue();
		});
	content()
		.querySelectorAll("[data-start]")
		.forEach(
			(b) =>
				(b.onclick = (e) =>
					act(b.dataset.start, "queue_start", "Started", e.currentTarget)),
		);
	content()
		.querySelectorAll("[data-cancel]")
		.forEach(
			(b) =>
				(b.onclick = (e) =>
					act(b.dataset.cancel, "queue_cancel", "Canceled", e.currentTarget)),
		);
	content()
		.querySelectorAll("[data-retry]")
		.forEach(
			(b) =>
				(b.onclick = (e) =>
					act(b.dataset.retry, "queue_retry", "Requeued", e.currentTarget)),
		);
	content()
		.querySelectorAll("[data-log]")
		.forEach(
			(b) =>
				(b.onclick = () =>
					run(() =>
						api(
							`/api/queue/${encodeURIComponent(b.dataset.log)}/log?lines=300`,
						),
					).then((d) => {
						$("#q-log").innerHTML =
							`<div class="card"><div class="label">Log · ${short(d.id, 8)} · ${pill(d.status)}</div><div class="logbox">${esc(d.log || "(no log yet)")}</div></div>`;
						$("#q-log").scrollIntoView({
							behavior: "smooth",
							block: "nearest",
						});
					})),
		);
}

// ---- Config (MCP + profiles editor) ---------------------------------------

let configFile = "mcp.json";

async function renderConfig() {
	const [mcp, profiles] = await Promise.all([
		api("/api/mcp"),
		api("/api/profiles"),
	]);
	const mcpRows = mcp
		.map(
			(m) =>
				`<tr><td class="mono">${esc(m.name)}</td><td>${pill(m.kind)}</td><td class="mono">${esc(m.url)}</td></tr>`,
		)
		.join("");
	const fileOpts = [
		`<option value="mcp.json">mcp.json</option>`,
		...profiles.map(
			(p) =>
				`<option value="profiles/${esc(p.name)}.json">profiles/${esc(p.name)}.json</option>`,
		),
	].join("");

	content().innerHTML = `
    <h1>Config</h1>
    <p class="sub">Edit the canonical sources, then Sync — <span class="mono">mcp-sync &amp;&amp; agents-sync</span> propagates to Claude + Codex.</p>
    <div class="cards">
      <div class="card"><div class="label">MCP servers</div><div class="kpi">${mcp.length}</div></div>
      <div class="card"><div class="label">Profiles</div><div class="kpi">${profiles.length}</div></div>
    </div>
    <table style="margin-bottom:18px">
      <thead><tr><th>MCP server</th><th>Kind</th><th>URL</th></tr></thead>
      <tbody>${mcpRows || `<tr><td colspan="3" class="empty">none</td></tr>`}</tbody>
    </table>
    <div class="row" style="margin-bottom:8px; align-items:flex-end">
      <div class="field"><label>Edit file</label><select id="cfg-file">${fileOpts}</select></div>
      <div class="spacer"></div>
      <button class="btn" id="cfg-save">Save</button>
      <button class="btn primary" id="cfg-save-sync">Save &amp; Sync</button>
    </div>
    <textarea id="cfg-text" spellcheck="false">Loading…</textarea>`;

	const sel = $("#cfg-file");
	sel.value = configFile;
	const load = async () => {
		configFile = sel.value;
		$("#cfg-text").value = await run(() => readDoc(configFile));
	};
	sel.onchange = load;
	await load();

	const save = async () => {
		const text = $("#cfg-text").value;
		if (configFile.endsWith(".json")) {
			try {
				JSON.parse(text);
			} catch (e) {
				toast("Invalid JSON: " + e.message, true);
				return false;
			}
		}
		await run(() => writeDoc(configFile, text));
		return true;
	};
	$("#cfg-save").onclick = (e) =>
		busy(e.currentTarget, save).then(
			(ok) => ok && toast("Saved " + configFile),
		);
	$("#cfg-save-sync").onclick = (e) =>
		busy(e.currentTarget, save).then((ok) => {
			if (!ok) return;
			toast("Saved — syncing…");
			run(() => action("sync")).then((r) =>
				toast(r.ok ? "Saved & synced" : "Sync failed", !r.ok),
			);
		});
}

// ---- Memory (markdown notes) ----------------------------------------------

let memoryFile = "";

async function renderMemory() {
	const files = await listMemory();
	if (!memoryFile && files.length) memoryFile = files[0];
	const opts = files
		.map(
			(f) =>
				`<option value="${esc(f)}">${esc(f.replace("assistant/memory/", ""))}</option>`,
		)
		.join("");

	content().innerHTML = `
    <h1>Memory</h1>
    <p class="sub">Durable, jj-versioned markdown. Append dated lines to Timelines rather than overwriting, so staleness stays visible.</p>
    <div class="row" style="margin-bottom:8px; align-items:flex-end">
      <div class="field"><label>Note</label><select id="mem-file">${opts || `<option>(none)</option>`}</select></div>
      <div class="spacer"></div>
      <button class="btn primary" id="mem-save">Save</button>
    </div>
    <textarea id="mem-text" spellcheck="false">${files.length ? "Loading…" : "No memory notes found."}</textarea>`;

	if (!files.length) return;
	const sel = $("#mem-file");
	sel.value = memoryFile;
	const load = async () => {
		memoryFile = sel.value;
		$("#mem-text").value = await run(() => readDoc(memoryFile));
	};
	sel.onchange = load;
	await load();
	$("#mem-save").onclick = () =>
		run(() => writeDoc(memoryFile, $("#mem-text").value)).then(() =>
			toast("Saved " + memoryFile.replace("assistant/memory/", "")),
		);
}

// ---- connection switcher --------------------------------------------------

async function loadConnections() {
	const data = await invoke("list_connections");
	const sel = $("#conn-select");
	sel.innerHTML = data.connections
		.map(
			(c) =>
				`<option value="${esc(c.name)}" ${c.active ? "selected" : ""}>${esc(c.name)}${c.has_token ? " 🔑" : ""}</option>`,
		)
		.join("");
	sel.onchange = async () => {
		await run(() => invoke("set_active", { name: sel.value }));
		toast(`Switched to ${sel.value}`);
		refreshCurrent();
		pollHealth();
	};
}

async function pollHealth() {
	const el = $("#conn-status");
	try {
		const h = await invoke("health");
		el.textContent = h.ok ? "● connected" : "● offline";
		el.className = "status " + (h.ok ? "ok" : "err");
	} catch {
		el.textContent = "● offline";
		el.className = "status err";
	}
}

// ---- boot -----------------------------------------------------------------

function wireNav() {
	document
		.querySelectorAll(".nav")
		.forEach((b) => (b.onclick = () => select(b.dataset.panel)));
}

async function main() {
	wireNav();
	await loadConnections();
	await pollHealth();
	await select("runs");

	// Live updates pushed from the Rust poller.
	listen("snapshot", (e) => {
		const snap = e.payload || {};
		updateApprovalBadge(snap.pending_approvals || 0);
		if (current === "runs" || current === "approvals" || current === "queue")
			refreshCurrent();
	});
	listen("refresh", () => refreshCurrent());
	listen("offline", () => {
		$("#conn-status").textContent = "● offline";
		$("#conn-status").className = "status err";
	});
}

main();
