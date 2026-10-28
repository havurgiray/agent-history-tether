// aht's window on Windows and Linux.  A front-end only: every action runs one
// of the aht commands (`aht … --json`) through the local server, the same
// ones the Mac app and the terminal use.  Everything shown is built with
// textContent: histories can hold anything, so no text becomes HTML.
"use strict";

// ---- small helpers ------------------------------------------------------------

// append() skips what is not there, so a part shown only sometimes can be
// written as `cond ? h(…) : null` (the DOM would write "null")
const domAppend = Element.prototype.append;
Element.prototype.append = function (...kids) {
  return domAppend.apply(this, kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
};

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "text") e.textContent = v;
    else if (k === "class") e.className = v;
    else if (k === "style") e.style.cssText = v;        // through the DOM: the page allows no style attributes
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "checked" || k === "disabled" || k === "value" || k === "selected") e[k] = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    e.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return e;
}
const $ = (s, el = document) => el.querySelector(s);
const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };
const base = (p) => (p || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() || p;
const parent = (p) => { const s = (p || "").replace(/[\\/]+$/, ""); const i = Math.max(s.lastIndexOf("/"), s.lastIndexOf("\\")); return i > 0 ? s.slice(0, i) : s; };
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const AGENTS = { claude: "Claude Code", kimi: "Kimi Code", codex: "Codex", agy: "Antigravity",
  vibe: "Mistral Vibe", gemini: "Gemini CLI", cursor: "Cursor", opencode: "OpenCode", copilot: "Copilot" };
// the agents a project can be switched to (the core's SWITCH_TARGETS), as
// many as are installed (status.agent_clis)
const SWITCH_TO = ["claude", "kimi", "codex", "agy", "vibe"];
// a computer's system as the core names it (Python's platform.system())
const SYSTEMS = { Darwin: "macOS", Linux: "Linux", Windows: "Windows" };

function tilde(p) {
  const home = S.status.home || "";
  return home && p && (p === home || p.startsWith(home + "/") || p.startsWith(home + "\\"))
    ? "~" + p.slice(home.length) : p;
}
function when(t) {
  if (!t) return "—";
  const d = typeof t === "number" ? new Date(t * 1000) : new Date(t);
  return isNaN(d) ? String(t) : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
/** A time of day for today, else date and time. */
function clock(t) {
  const d = typeof t === "number" ? new Date(t * 1000) : new Date(t);
  if (isNaN(d)) return String(t || "");
  return d.toDateString() === new Date().toDateString() ? d.toLocaleTimeString(undefined, { timeStyle: "short" }) : when(t);
}
function ago(t) {
  if (!t) return "";
  const d = typeof t === "number" ? new Date(t * 1000) : new Date(t);
  if (isNaN(d)) return "";
  const s = (d - Date.now()) / 1000, a = Math.abs(s);
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (a < 60) return "just now";
  if (a < 3600) return rtf.format(Math.round(s / 60), "minute");
  if (a < 86400) return rtf.format(Math.round(s / 3600), "hour");
  if (a < 86400 * 45) return rtf.format(Math.round(s / 86400), "day");
  return d.toLocaleDateString();
}
function bytes(n) {
  n = Number(n) || 0;
  for (const u of ["bytes", "KB", "MB", "GB"]) { if (n < 1024 || u === "GB") return `${n < 10 && u !== "bytes" ? n.toFixed(1) : Math.round(n)} ${u}`; n /= 1024; }
}

// ---- talking to aht -----------------------------------------------------------

// What the window opens on, when the tray opened it for one project
// (Projects brought here ▸ Send Back…): p=<its path>&do=show|send-back
// after #, read before the address is cleaned below.
const GO = (() => {
  try {
    const q = new URLSearchParams(location.hash.slice(1));
    return q.get("p") ? { path: q.get("p"), do: q.get("do") || "show" } : null;
  } catch (e) { return null; }
})();
// The key that lets this page use aht's API. aht puts it after # in the
// address it opens, a part no server sees; it is kept for a reload, then
// taken out of the address.
const KEY = (() => {
  const m = /[#&]k=([\w-]+)/.exec(location.hash);
  let k = m ? m[1] : "";
  try {
    if (k) sessionStorage.setItem("aht-key", k);
    else k = sessionStorage.getItem("aht-key") || "";
  } catch (e) { /* no storage: a reload then needs the window opened again */ }
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  return k;
})();

let LOST = false;
/** What every request answers once the server is gone. */
const gone = () => ({ ok: false, code: -1, out: "", err: "aht's window server did not answer.", json: null });
async function talk(path, init) {
  if (LOST) return gone();
  try {
    const r = await fetch(path, init);
    // a door that stays shut (a plain-text 403), not a refused command
    if (r.status === 403 && !(r.headers.get("Content-Type") || "").startsWith("application/json")) {
      lostConnection();
      return gone();
    }
    return await r.json().catch(() => ({}));
  } catch (e) {                       // the server has stopped
    lostConnection();
    return gone();
  }
}
const post = (path, body) => talk(path, { method: "POST", headers: { "Content-Type": "application/json", "X-AHT": KEY },
  body: JSON.stringify(body || {}) });
const get = (path) => talk(path, { headers: { "X-AHT": KEY } });
/** One aht command -> {ok, code, out, err, json}. */
const run = (args) => post("/api/run", { args });
/** One aht command's JSON answer ({} if none). */
async function J(...args) { const a = await run(args); return a.json || {}; }

/** A long command: started, then followed until done (with its progress). */
async function job(args, label, follow) {
  const { job: id } = await post("/api/start", { args, follow: !!follow });
  if (!id) return { ok: false, out: "", err: "could not start", json: null };
  for (;;) {
    await new Promise((r) => setTimeout(r, 600));
    const j = await get("/api/job?id=" + id);
    if (LOST) return gone();
    if (j.error) return { ok: false, out: "", err: j.error, json: null };
    if (j.progress) setBusy(`${j.progress.stage || label}${j.progress.percent != null ? ` — ${Math.round(j.progress.percent)} %` : ""}`);
    if (j.done) return j.answer || {};
  }
}

let busyCount = 0;
function setBusy(text) { const b = $("#busy"); clear(b); if (text) b.append(h("span", { class: "spin" }), text); }
async function busy(text, fn) {
  busyCount++; setBusy(text);
  try { return await fn(); } finally { if (--busyCount === 0) setBusy(""); }
}
function toast(text, ms = 4000) {
  const t = $("#toast"); t.textContent = text; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, ms);
}
function lost() {
  $("#summary").textContent = "";
  $("#watching").hidden = true;
  $("#banner").hidden = true;
  clear($("#main")).append(h("div", { class: "box" }, h("h2", { text: "This window lost its connection to aht" }),
    h("p", { text: "aht's window server has stopped, for example after an upgrade or a long time without use. Open the window again from aht's tray icon, or run “aht window”." })));
}
/** Once, when the server is gone: nothing open stays waiting for it. */
function lostConnection() {
  if (LOST) return;
  LOST = true;
  document.querySelectorAll(".dialog-back").forEach((d) => d.remove());
  closeMenus();
  closeSheet();
  lost();
}
/** Why a plan cannot go ahead, from its blockers and error. */
function problems(d) {
  const b = [...(d.blockers || [])];
  if (d.error) b.push(d.error);
  return b.length ? b.join("\n\n") : null;
}

// ---- dialogs ------------------------------------------------------------------

/** A sheet over the window: head, body, buttons. Returns its parts. */
function sheet(title, topic, width) {
  const back = $("#sheet-back"), s = clear($("#sheet"));
  s.style.width = width ? `min(${width}px, 100%)` : "";
  const head = h("div", { class: "head" }, h("h1", { text: title }), topic ? helpBtn(topic) : null);
  const body = h("div", { class: "body" });
  const foot = h("div", { class: "foot" });
  s.append(head, body, foot);
  back.hidden = LOST;                 // nothing in it could work now
  return { head, body, foot, close: closeSheet };
}
function closeSheet() { $("#sheet-back").hidden = true; clear($("#sheet")); }
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (document.querySelector(".dialog-back")) document.querySelector(".dialog-back").remove();
    else if (!$("#sheet-back").hidden) closeSheet();
    closeMenus();
  }
});

/** A small question above everything: resolves to the label pressed, or
 * null.  `extra`: more under the text (a box with a Copy button, say). */
function ask(title, body, buttons = ["Cancel", "OK"], extra) {
  return new Promise((resolve) => {
    if (LOST) return resolve(null);   // the window says why nothing works
    const back = h("div", { class: "dialog-back", style: "position:fixed;inset:0;background:rgba(0,0,0,.3);z-index:70;display:flex;align-items:center;justify-content:center;padding:20px" });
    const done = (v) => { back.remove(); resolve(v); };
    const box = h("div", { class: "box", style: "max-width:520px;width:100%;max-height:100%;overflow:auto;box-shadow:var(--shadow)" },
      h("h2", { text: title, style: "margin-top:0" }),
      body ? h("p", { text: body, style: "white-space:pre-wrap" }) : null,
      extra && [].concat(extra).some(Boolean) ? h("div", { class: "stack" }, extra) : null,
      h("div", { class: "row", style: "justify-content:flex-end;margin-top:10px" },
        buttons.map((b, i) => h("button", { text: b, class: i === buttons.length - 1 ? "primary" : "",
          onclick: () => done(i === 0 && buttons.length > 1 ? null : b) }))));
    back.append(box);
    document.body.append(back);
    box.querySelector("button.primary")?.focus();
  });
}
const confirmIt = async (title, body, ok, extra) => (await ask(title, body, ["Cancel", ok], extra)) === ok;
const tell = (title, body) => ask(title, body, ["OK"]);

/** A button with a menu under it. */
function menu(label, items, opts = {}) {
  const wrap = h("span", { class: "menu" });
  const btn = h("button", { text: label + " ▾", disabled: opts.disabled, class: opts.small ? "small" : null });
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = wrap.querySelector(".items");
    closeMenus();
    if (open) return;
    const list = h("div", { class: "items" + (opts.right ? " right" : "") });
    for (const it of items) {
      if (it === "-") { list.append(h("hr")); continue; }
      if (!it) continue;
      list.append(h("button", { text: it[0], disabled: it[2], onclick: () => { closeMenus(); it[1](); } }));
    }
    wrap.append(list);
    // fixed to the window, so no scrolling pane cuts it off; up when there is
    // no room below
    const r = btn.getBoundingClientRect(), lh = list.offsetHeight, lw = list.offsetWidth;
    list.style.position = "fixed";
    list.style.left = Math.max(8, Math.min(opts.right ? r.right - lw : r.left, innerWidth - lw - 8)) + "px";
    list.style.top = (r.bottom + 4 + lh > innerHeight - 8 ? Math.max(8, r.top - 4 - lh) : r.bottom + 4) + "px";
    list.style.right = "auto";
    list.style.marginTop = "0";
  });
  wrap.append(btn);
  return wrap;
}
function closeMenus() { document.querySelectorAll(".menu > .items").forEach((m) => m.remove()); }
document.addEventListener("click", closeMenus);

// ---- markdown, the way aht writes it -----------------------------------------------

function inline(text) {
  const frag = document.createDocumentFragment();
  // `code`, **bold**, *em* / _em_, [text](https://…), and search marks \x02…\x03
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\b_[^_]+_\b)|(\[[^\]]+\]\([^)\s]+\))|(\x02[^\x03]*\x03)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) frag.append(text.slice(last, m.index));
    const t = m[0];
    if (m[1]) frag.append(h("code", { text: t.slice(1, -1) }));
    else if (m[2]) frag.append(h("strong", {}, inline(t.slice(2, -2))));
    else if (m[3] || m[4]) frag.append(h("em", {}, inline(t.slice(1, -1))));
    else if (m[5]) {
      const [, label, url] = t.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
      const a = h("a", { href: "#", text: label });
      a.addEventListener("click", (e) => { e.preventDefault(); if (/^https:\/\//.test(url)) post("/api/open-url", { url }); });
      frag.append(a);
    } else frag.append(h("mark", { text: t.slice(1, -1) }));
    last = m.index + t.length;
  }
  if (last < text.length) frag.append(text.slice(last));
  return frag;
}

function md(text, skipTitle) {
  const root = h("div", { class: "md" });
  const lines = String(text || "").replace(/\r/g, "").split("\n");
  const start = (l) => /^(#{1,6} |```|\s*[-*] |\s*\d+\. |> ?|\|)/.test(l) || l.trim() === "";
  for (let i = 0; i < lines.length;) {
    const l = lines[i];
    if (/^```/.test(l)) {
      const buf = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++; root.append(h("pre", { text: buf.join("\n") }));
    } else if (/^#{1,6} /.test(l)) {
      const n = l.match(/^#+/)[0].length; i++;
      if (!(skipTitle && n === 1)) root.append(h("h" + Math.min(n + (n === 1 ? 0 : 0), 4), {}, inline(l.replace(/^#+ /, ""))));
    } else if (/^\s*([-*]|\d+\.) /.test(l)) {
      const ordered = /^\s*\d+\./.test(l);
      const list = h(ordered ? "ol" : "ul");
      while (i < lines.length && /^\s*([-*]|\d+\.) /.test(lines[i])) {
        let item = lines[i++].replace(/^\s*([-*]|\d+\.) /, "");
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*]|\d+\.) /.test(lines[i])) item += " " + lines[i++].trim();
        list.append(h("li", {}, inline(item)));
      }
      root.append(list);
    } else if (/^> ?/.test(l)) {
      const buf = [];
      while (i < lines.length && /^> ?/.test(lines[i])) buf.push(lines[i++].replace(/^> ?/, ""));
      root.append(h("blockquote", {}, md(buf.join("\n"))));
    } else if (/^\|/.test(l)) {
      const rows = [];
      while (i < lines.length && /^\|/.test(lines[i])) rows.push(lines[i++]);
      const cells = (r) => r.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const t = h("table");
      rows.filter((r) => !/^\|[\s:|-]+\|$/.test(r)).forEach((r, k) =>
        t.append(h("tr", {}, cells(r).map((c) => h(k === 0 ? "th" : "td", {}, inline(c))))));
      root.append(t);
    } else if (l.trim() === "") {
      i++;
    } else {
      const buf = [l]; i++;
      while (i < lines.length && !start(lines[i])) buf.push(lines[i++]);
      root.append(h("p", {}, inline(buf.join(" "))));
    }
  }
  return root;
}

// ---- the guide ------------------------------------------------------------------

let GUIDE = null;
async function guideTopics() {
  if (!GUIDE) {
    const { text } = await get("/api/guide");
    const topics = [];
    let cur = { title: "Introduction", text: [] };
    for (const l of String(text || "").split("\n")) {
      if (/^## /.test(l)) { topics.push(cur); cur = { title: l.slice(3).trim(), text: [] }; }
      else cur.text.push(l);
    }
    topics.push(cur);
    if (!text) return topics;
    GUIDE = topics.map((t) => ({ title: t.title, text: t.text.join("\n") }));
  }
  return GUIDE;
}
async function openGuide(topic) {
  const topics = await guideTopics();
  let pick = topics.find((t) => topic && t.title.toLowerCase().startsWith(topic.toLowerCase())) || topics[0];
  const s = sheet("aht guide", null, 980);
  const nav = h("nav"), art = h("article");
  const show = (t) => {
    pick = t;
    nav.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.textContent === t.title));
    clear(art).append(h("h1", { text: t.title }), md(t.text, true));
    art.scrollTop = 0;
  };
  topics.forEach((t) => nav.append(h("button", { text: t.title, onclick: () => show(t) })));
  s.body.append(h("div", { class: "guide" }, nav, art));
  s.foot.append(h("span", { class: "spacer" }), h("button", { text: "Close", class: "primary", onclick: closeSheet }));
  show(pick);
}
const helpBtn = (topic) => h("button", { class: "help icon", text: "?", title: `How this works (guide: ${topic})`,
  onclick: (e) => { e.stopPropagation(); openGuide(topic); } });

// ---- state ----------------------------------------------------------------------

const S = { tab: "projects", status: {}, config: {}, explicit: {}, projects: [], selection: null, filter: "",
  board: null, boardAt: null, query: "", hits: null, notes: {}, loaded: false, movers: {} };
const ON_WINDOWS = () => (S.status.platform || "").startsWith("win");
const ON_MAC = () => S.status.platform === "darwin";
const CAN_HAND_OVER = () => !!(S.status.handover || {}).supported;
// asking other machines (ssh alone); an older core says only "supported"
const CAN_REACH = () => { const ho = S.status.handover || {}; return "can_reach" in ho ? !!ho.can_reach : !!ho.supported; };
// what a PC does with a project and the other machines, said where Hand Over
// would be when this aht cannot hand projects over: with a Mac or Linux
// machine to ask, and without one
const FROM_WINDOWS = "With Machines ▾, Pick Up brings this project's latest work on another machine here as a summary, and Leave a Note leaves a summary of your work here on that machine before you go. Git moves the files.";
const FROM_WINDOWS_NONE = "Add your Mac or Linux machines in the Machines tab: then you can pick up a project's work from them here, and leave a note on them before you go.";
// …and at the top of the Machines tab
const PC_MACHINES = "From this PC you can see, search and watch your other machines, pick up a project's work from them and leave a note on them.";
const flag = (k, d = true) => (k in S.config ? !!S.config[k] : d);
/** What copies files to and from another machine (`handover_transfer`):
 * "auto" picks rsync where both machines have it and neither is Windows,
 * else aht's own copy. */
const TRANSFER = { auto: "rsync where both machines have it, else aht's own copy", rsync: "rsync", aht: "aht's own copy" };
const MOVER = { rsync: "rsync", aht: "aht's own copy" };
const transferMode = () => (TRANSFER[S.config.handover_transfer] ? S.config.handover_transfer : "auto");
/** The mover a machine gets: what `remote check --json` said (`transfer`)
 * while the setting is still the one it was asked under; else what is known
 * here: Windows on either side, or no rsync 3 on this machine, is aht's own
 * copy.  null: rsync if the machine has it, which only asking it tells. */
function moverFor(name, r) {
  const mode = transferMode(), said = S.movers[name];
  if (said && said.mode === mode) return said.transfer;
  if (mode !== "auto") return mode;
  const rs = parseInt(String((S.status.handover || {}).rsync || ""), 10);
  return ON_WINDOWS() || (r || {}).system === "Windows" || !(rs >= 3) ? "aht" : null;
}
/** "box: rsync · pc: aht's own copy", for every machine set up. */
function moversLine() {
  return Object.entries((S.status.handover || {}).remotes || {}).sort(([a], [b]) => a.localeCompare(b))
    .map(([n, r]) => { const t = moverFor(n, r); return `${n}: ${t ? MOVER[t] || t : "rsync if it has it, else aht's own copy"}`; }).join(" · ");
}
/** Remember what `remote check --json` said each machine gets. */
function noteMovers(d) {
  for (const x of (d && d.machines) || []) if (x.remote && MOVER[x.transfer]) S.movers[x.remote] = { mode: transferMode(), transfer: x.transfer };
}
/** Keep in sync, paused (`mirror_paused`: {reason, at, remote}): Release
 * pauses it, so no sync replaces the copy left on that machine until the
 * user turns it back on.  null while it runs. */
const syncPaused = (p) => (p.mirror && p.mirror_paused ? p.mirror_paused : null);
/** A folder here that another machine keeps in sync (`copy_of`: {from,
 * kind}, from this machine's ~/.aht/remote/copies.json; `from`: that
 * machine's own name), or null. */
const copyOf = (p) => (p.copy_of && typeof p.copy_of === "object" && p.copy_of.from ? p.copy_of : null);
/** A copy here that goes back with Send Back: brought here (Bring Here), or
 * handed over here from another machine. */
const sendsBack = (c) => !!c && (c.kind === "brought" || c.kind === "handover");
/** …and this machine has no name for its home (`copy_of.remote` null):
 * Send Back needs that machine added first. */
const noName = (c) => !!c && "remote" in c && !c.remote;
/** A machine set up here (its `status` row), or null. */
const remoteRow = (name) => (name && ((S.status.handover || {}).remotes || {})[name]) || null;
/** Whether aht can ask a machine (its `status` row): a Mac or Linux one,
 * yes.  A Windows PC answers once aht there (or its own copy, with the
 * PC's Python) answered over ssh: the core says so in the row (`answers`;
 * when false, why in `answers_why`: "install aht on pc: …", "not asked
 * yet: …").  A core that does not say cannot ask a PC. */
const answers = (r) => !!r && (r.system !== "Windows" || r.answers === true);
/** Why aht cannot ask a PC, in the core's words. */
const pcWhy = (r) => { const t = String((r && r.answers_why) || "").trim(); return !t ? "aht cannot ask a Windows machine yet." : /[.!?]$/.test(t) ? t : t + "."; };
/** The guide's section on setting a PC up so that aht can ask it. */
const PC_SETUP = "A Windows PC that answers";
const pcSetup = () => h("div", { class: "row small pc-setup" }, h("span", { class: "dim", text: "How to set a PC up so that aht can ask it:" }), helpBtn(PC_SETUP));
/** …and its home is a PC (`copy_of.system`).  Send Back returns it while
 * that PC answers; else it goes back only from there (Take Back on the PC). */
const pcHome = (c) => !!c && c.system === "Windows";
/** …and that PC does not answer: no Send Back from here. */
const pcHomeMute = (c) => pcHome(c) && !answers(remoteRow(c.remote));
/** A project of this machine's that is on another one: {name, system, pc:
 * a Windows PC holds it, there: the holder brought it there
 * (`away.driven_by`), since, agent: the agent working on it there
 * (`away.agent`, in words), take: Take Back can fetch it}.  What a PC that
 * aht cannot ask holds goes back only with Send Back there, or Release
 * here; so does what a machine this one has no name for brought there
 * (`away_remote` null). */
function awayOf(p) {
  if (!p.away) return null;
  const r = remoteRow(p.away_remote) || {};
  const there = p.away_driven_by === "there", system = p.away_system || r.system || null;
  return { name: p.away_remote || p.away_holder || p.away, system, pc: system === "Windows" || !!p.away_arrival, there, since: p.away_since,
    agent: p.away_arrival ? null : awayAgentLabel(p),
    take: CAN_HAND_OVER() && (system !== "Windows" || answers(remoteRow(p.away_remote))) && !(there && !p.away_remote) };
}

async function refresh() {
  const [st, cfg, pj] = await Promise.all([J("status", "--json"), J("config", "--json"), J("projects", "--json")]);
  if (st.version) S.status = st;
  if (cfg.effective) {
    S.config = cfg.effective;
    S.explicit = cfg.explicit || {};
  }
  if (pj.projects) {
    S.projects = pj.projects;
    S.limitSwitchTo = pj.limit_switch_to;
  }
  S.status.home = S.status.home || guessHome();
  S.loaded = true;
  drawTop();
  // not while something is typed (a checkbox just clicked keeps the focus too)
  if (!document.querySelector("#main input:not([type=checkbox]):not([type=radio]):focus, #main textarea:focus, #main select:focus")) draw();
}
function guessHome() {
  const r = (S.status.watch_roots || [])[0] || "";
  const m = r.match(/^(.*?[\\/](?:Users|home)[\\/][^\\/]+)/i);
  return m ? m[1] : "";
}
async function setConfig(key, value, reload) {
  S.config[key] = value;
  const v = typeof value === "string" ? value : JSON.stringify(value);
  const r = await run(["config", "--set", `${key}=${v}`].concat(reload ? [] : ["--no-reload"]));
  // a value the core refuses (exit 2: agent_permission_flags that ask for
  // more than their level, say): its words, and the setting as it was
  const said = ((r.err || "") + (r.out || "")).trim();
  if (!r.ok && r.code > 0) {
    await refresh();
    draw();
    return tell("The setting was not saved", said || "aht refused it.");
  }
  refresh();
}

// ---- the top of the window ---------------------------------------------------------

const TABS = [["projects", "Projects"], ["sessions", "Sessions"], ["search", "Search"], ["machines", "Machines"], ["settings", "Settings"]];
function drawTop() {
  const nav = clear($("#tabs"));
  const waiting = S.projects.filter((p) => p.open === "waiting").length;
  for (const [id, label] of TABS) {
    nav.append(h("button", { role: "tab", "aria-selected": String(S.tab === id),
      text: id === "sessions" && waiting ? `${label} (${waiting})` : label,
      onclick: () => { S.tab = id; draw(); drawTop(); } }));
  }
  const st = S.status;
  const missing = st.missing || 0;
  const known = !!st.version && !LOST;     // nothing is said before the first status
  $("#summary").textContent = known ? `${plural(st.tracked || 0, "tracked project")}${missing ? ` · ${missing} missing` : ""}${st.hook_installed === false ? " · hook MISSING" : ""}` : "";
  const w = st.watcher || {};
  const on = !!w.running;
  $("#watching").hidden = !known;
  $("#watching .dot").classList.toggle("off", !on);
  $("#watching .label").textContent = on ? "watching" : "paused";
  $("#ver").textContent = st.version ? `aht ${st.version}` : "";
  const u = st.update || {};
  const banner = $("#banner");
  if (u.newer && !LOST) {
    clear(banner).append(h("span", { text: `aht ${u.latest} is out.` }),
      h("button", { class: "small", text: "What's New…", onclick: showUpdate }));
    banner.hidden = false;
  } else banner.hidden = true;
  document.title = waiting ? `aht (${waiting} waiting)` : "aht";
}

function draw() {
  if (LOST) return lost();
  const m = clear($("#main"));
  if (!S.loaded) { m.append(h("p", { class: "dim" }, h("span", { class: "spin" }), "Loading…")); return; }
  ({ projects: drawProjects, sessions: drawSessions, search: drawSearch, machines: drawMachines,
     settings: drawSettings })[S.tab](m);
}

// ---- Projects -------------------------------------------------------------------

function projState(p) {
  if (p.handing) return ["handover unfinished", "waiting"];
  // the agent working on it there (`away_agent`), when the core names it
  // handed over to a PC: nothing runs there until Continue here
  if (p.away && p.away_arrival) return [`Continue here waits on ${awayOf(p).name}`, "working"];
  if (p.away) return [(awayOf(p).there ? `on ${awayOf(p).name}` : `handed over to ${p.away}`) + (awayAgentLabel(p) ? ` (${awayAgentLabel(p)})` : ""), "working"];
  if (!p.exists) return ["folder gone", "waiting"];
  if (p.open === "waiting") return ["waiting for you", "waiting"];
  if (p.open === "working") return ["working", "working"];
  if (p.open === "idle") return ["open", ""];
  const x = crossing(p);
  if (x && x.kind === "note" && x.arrived) return [`${x.back ? "back" : "note"} from ${x.remote || x.machine || "another machine"}`, "working"];
  if (p.limit) return ["usage limit", "waiting"];
  // a pause that asks something (the copy there was changed, say) waits for you
  if (syncPaused(p)) return ["sync paused", asksForSync(p) ? "waiting" : ""];
  const c = copyOf(p);
  if (c) return [{ brought: `brought from ${c.from}`, handover: `handed over from ${c.from}` }[c.kind] || `copy from ${c.from}`, ""];
  return ["", ""];
}

function drawProjects(m) {
  const f = S.filter.toLowerCase();
  const list = S.projects.filter((p) => !f || p.real_path.toLowerCase().includes(f))
    .sort((a, b) => String(b.last_activity || "").localeCompare(String(a.last_activity || "")));
  const filter = h("input", { type: "search", placeholder: "Filter projects", value: S.filter,
    oninput: (e) => { S.filter = e.target.value; const pos = e.target.selectionStart; draw(); const i = $("#main input[type=search]"); i.focus(); i.setSelectionRange(pos, pos); } });
  const tbody = h("tbody");
  for (const p of list) {
    const [state, cls] = projState(p);
    tbody.append(h("tr", { class: p.real_path === S.selection ? "picked" : "",
      onclick: () => { S.selection = p.real_path; draw(); },
      ondblclick: () => { S.selection = p.real_path; if (p.exists && !p.away && !p.handing) continueHere(p); } },
      h("td", {}, h("strong", { text: base(p.real_path) }), " ", h("span", { class: "dim small", text: tilde(parent(p.real_path)) })),
      h("td", {}, state ? h("span", { class: "badge " + cls, text: state }) : ""),
      h("td", { class: "dim", text: ago(p.last_activity) }),
      h("td", { class: "dim small", text: (p.agents || []).map((a) => AGENTS[a] || a).join(", ") })));
  }
  const table = h("table", { class: "list" }, h("thead", {}, h("tr", {},
    h("th", { text: "Project" }), h("th", { text: "State" }), h("th", { text: "Last used" }), h("th", { text: "Agents" }))), tbody);
  const look = menu("Look Back", [["Loose Ends…", openLooseEnds], ["Report…", openReport]], { right: true });
  // a project of another machine's, brought here to work on (Bring Here)
  const from = askable();
  const bring = from.length ? menu("Bring Here", from.map((n) => [`From ${n}…`, () => bringList(n)]), { right: true }) : null;
  const top = h("div", { class: "row" }, filter, h("span", { class: "grow" }),
    (S.status.missing || S.status.orphan_claude_stores) ? h("button", { text: "Tidy Up…", onclick: openTidy }) : null, bring, look);
  m.append(h("div", { class: "split" }, top,
    h("div", { class: "listpane" }, list.length ? table : h("p", { class: "dim", style: "padding:12px",
      text: S.projects.length ? "No project matches." : "No project tracked yet: aht takes them on as you work, or use Settings → Run Setup Again." })),
    detail()));
}

function detail() {
  const p = S.projects.find((x) => x.real_path === S.selection);
  const d = h("div", { class: "detail stack" });
  if (!p) { d.append(h("p", { class: "dim", text: "Select a project to continue a session, see what changed, or look back." })); return d; }
  const aw = awayOf(p);
  const st = p.handing ? `handover to ${handing(p).to} unfinished`
    : p.away && p.away_arrival ? `Continue here waits on ${aw.name}${p.away_since ? ", " + ago(p.away_since) : ""}`
    : p.away ? `${aw.there ? "on " + aw.name : "handed over to " + p.away}${p.away_since ? ", " + ago(p.away_since) : ""}${awayAgentLabel(p) ? `; ${awayAgentLabel(p)} works on it there` : ""}`
    : !p.exists ? "the folder is gone; its histories are safe"
    : `${plural(p.sessions || 0, "session")}, ${bytes(p.bytes)} of history`;
  d.append(h("div", { class: "row" }, h("strong", { text: base(p.real_path) }), h("span", { class: "dim", text: st })),
    h("div", { class: "dim small mono", text: tilde(p.real_path) }));
  if (p.handing) d.append(handingBanner(p));
  else if (!p.away && p.exists && syncPaused(p)) d.append(pausedBanner(p));
  // brought to another machine, or held by a PC: it comes back from there
  // (or, from a PC that answers, with Take Back here too)
  if (aw && !p.handing && (aw.there || !aw.take || aw.pc)) d.append(awayLine(p, aw));
  const copy = p.exists && !p.away ? copyOf(p) : null;
  if (copy) d.append(copyLine(copy, p));
  const relay = openRelay(p);
  if (relay) d.append(relayLine(p, relay));
  const across = crossing(p), line = across && crossingLine(p, across);
  if (line) d.append(line);
  const from = pickedUp(p);
  if (from) d.append(pickupLine(p, from));
  const row = h("div", { class: "row" });
  const handover = CAN_HAND_OVER() && (S.status.handover || {}).default_remote;
  if (p.away) {
    if (aw.take) row.append(h("button", { class: "primary", text: "Take Back…", onclick: () => takeBack(p) }));
    // the window aht runs the agent in there: its last screen lines
    if (aw.take && !aw.there && !aw.pc && p.away_window) row.append(h("button", { text: "Peek…", onclick: () => peekThere(p) }));
  } else if (p.exists) {
    // while a handover is unfinished, nobody knows yet where the work goes on
    const held = !!p.handing;
    // a copy of another machine's project goes back there (Send Back), not on
    if (CAN_HAND_OVER() && !sendsBack(copy)) {
      row.append(h("button", { text: handover ? `Hand Over to ${handover}…` : "Hand Over…", disabled: !handover || !!p.open || held,
        onclick: () => handOver(p) }));
      row.append(h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!p.mirror, disabled: !handover || held,
        onchange: (e) => keepInSync(p, e.target.checked) }), "Keep in sync" + (p.mirror ? ` with ${p.mirror}` : "")
        + (syncPaused(p) ? " (paused)" : "")));
    }
    row.append(h("button", { text: "Continue Session", disabled: !(p.sessions > 0) || held, onclick: () => continueHere(p) }));
    // with an open relay, giving the project back comes first
    const to = SWITCH_TO.filter((a) => (S.status.agent_clis || {})[a])
      .map((a) => [`Continue in ${AGENTS[a]}…`, () => switchAgent(p, a)]);
    row.append(menu("Switch Agent", [
      relay ? [`Hand Back to ${AGENTS[relay.from_agent] || relay.from_agent} (its own session)…`, () => handBack(p)] : null,
      relay && to.length ? "-" : null, ...to], { disabled: !(p.sessions > 0 || (p.agents || []).length) || held }));
    row.append(helpBtn("Continue in another agent"));
    const ms = askable();
    if (ms.length) row.append(machinesMenu(p, ms, held));
  }
  row.append(h("span", { class: "grow" }));
  if (p.exists) {
    row.append(menu("More", [
      ["Show Sessions…", () => openSessionList(p)],
      ["What Changed…", () => openChanges(p)],
      ["Undo a Session…", () => openUndo(p)],
      ["Journal", () => openJournal(p)],
      ["AI-Use Statement", () => openStatement(p)],
      ["Share a Session…", () => share(p)],
      "-",
      ["Project Rules…", () => openRules(p)],
      ["Check for Secrets", () => openSecrets(p)],
      "-",
      ["Second Opinion…", () => openOpinion(p)],
      CAN_HAND_OVER() ? ["Night Shift…", () => openNightShift(p), !handover] : null,
      p.away && CAN_HAND_OVER() ? [`Release from ${p.away_remote || p.away}…`, () => release(p)] : null,
      "-",
      [ON_WINDOWS() ? "Show in Explorer" : "Show in Files", () => post("/api/reveal", { path: p.real_path })],
    ], { right: true }), helpBtn("The window at a glance"));
  }
  d.append(row);
  if (p.exists && !p.away && !CAN_HAND_OVER() && CAN_REACH() && ON_WINDOWS()) d.append(h("p", { class: "dim small", text: askable().length ? FROM_WINDOWS : FROM_WINDOWS_NONE }));
  if (p.open && !p.away && !p.handing && CAN_HAND_OVER()) {
    d.append(h("p", { class: "warn small", text: p.open === "waiting"
      ? "An agent session in this project is waiting for you. Answer it in its terminal; the project cannot be handed over until it has finished and is closed."
      : "An agent session is open in this project. It can be handed over once it has finished and is closed." }));
  }
  if (p.limit && !p.away) {
    const t = S.limitSwitchTo;
    d.append(h("div", { class: "row" }, h("span", { class: "warn small", text: `Claude stopped at its usage limit${p.limit.resets ? "; it resets " + p.limit.resets : ""}.` }),
      t ? h("button", { class: "small", text: `Continue in ${AGENTS[t] || t}…`, onclick: () => switchAgent(p, t) }) : null));
  }
  const n = S.notes[p.real_path];
  if (n) {
    const text = typeof n === "string" ? n : n.text;
    if (text) d.append(h("pre", { text, style: "white-space:pre-wrap" }));
    if (n.file) d.append(h("button", { class: "small", text: ON_WINDOWS() ? "Show in Explorer" : "Show in Files",
      onclick: () => post("/api/reveal", { path: parent(n.file) }) }));
    if (n.parts) d.append(h("div", { class: "stack" }, n.parts));
  }
  return d;
}
/** A note under the project; `file`: one it names, with a button that shows
 * its folder; `parts`: more to show under it (names that cannot cross, say). */
const note = (p, text, file, parts) => {
  S.notes[p.real_path || p] = file || parts ? { text, file, parts } : text;
  draw();
};
/** Whether "Start aht's tray at login" can be turned on here: the core knows
 * how, and (on Linux) the tray can run. */
const loginWorks = () => { const a = S.status.autostart || {}; return !!a.supported && a.runs !== false; };

/** Continue a session in a new terminal window; when none opens, the line
 * aht printed is shown, to run by hand. */
async function resume(args) {
  const r = await run(["resume-here", ...args]);
  if (r.ok) return toast("Opened in a new terminal window.");
  const out = (r.out || "").trim(), err = (r.err || "").trim();
  tell("No terminal window opened", out ? "Run this in a terminal:\n\n" + out + (err ? "\n\n" + err : "")
    : err || "aht could not open a terminal window.");
}
async function continueHere(p) {
  await busy(`opening ${base(p.real_path)}…`, () => resume([p.real_path]));
}

/** A dry run's answer, or why there is none (an older aht that does not
 * know the option, say). */
async function dryRun(args) {
  const a = await run(args);
  return a.json || { error: ((a.err || "") + (a.out || "")).trim() || "aht gave no answer." };
}

// ---- the permission level the next agent starts in ----------------------------------
// Switch, Hand Back, Pick Up → Open in, Bring Here, Hand Over and the night
// shift (and their dry runs) carry `perm`: {agent, level, sandbox, flags,
// from, read, text}; null when nothing starts.  Levels in aht's words: ask
// (each agent's default), edits (edits run, commands ask), auto (routine
// runs, risky asks), never (never asks).  `read`: the level of the session
// the work comes from; `text`: the core's sentence, shown as given.  The next
// agent starts in its own equivalent, or in the next stricter level it has
// (`agent_permissions`: "follow", a fixed level, or "max:<level>"); aht never
// raises it by itself.  Never-ask is shown with a caution, not stopped: the
// user chose it.
const PERM_LEVELS = ["ask", "edits", "auto", "never"];
const PERM_NAME = { ask: "ask mode", edits: "edits mode", auto: "auto mode", never: "never-ask mode" };
const PERM_SAYS = { ask: "It asks before it acts, as it does by default.", edits: "Edits run without asking; commands ask first.",
  auto: "Routine steps run without asking; risky ones ask first.", never: "It never asks: every edit and command runs." };
const permRank = (l) => PERM_LEVELS.indexOf(l);
/** The Permissions setting: "follow", a level, or "max:<level>". */
function permSetting() {
  const v = String(S.config.agent_permissions || "follow");
  return PERM_NAME[v] || (v.startsWith("max:") && PERM_NAME[v.slice(4)]) ? v : "follow";
}
/** A level in words: "never-ask mode inside its sandbox". */
const permName = (level, sandbox) => PERM_NAME[level] + (sandbox && level === "never" ? " inside its sandbox" : "");
/** The level `agent` starts in, from a dry run: {level, sandbox, flags,
 * text (the core's), was (the level of the session the work comes from),
 * fell (no exact match: a stricter level), other}.  `other`: the core named
 * no level for this agent (Pick Up without --open, or another agent than
 * the one planned), only the level of the session there (`source.perm`):
 * the flags are the agent's own (null).  null: no level known (an older
 * core, or nothing starts). */
function permOf(d, agent) {
  if (!d || typeof d !== "object") return null;
  const by = d.perms && typeof d.perms === "object" ? d.perms : {};
  const own = agent && by[agent] && typeof by[agent] === "object" ? by[agent] : null;
  let p = own || (d.perm && typeof d.perm === "object" ? d.perm : null);
  if (p && agent && !own && (p.agent || d.target) && (p.agent || d.target) !== agent) p = null;
  let other = false;
  const src = d.source && typeof d.source === "object" && d.source.perm && typeof d.source.perm === "object" ? d.source.perm : null;
  if (!p && src && PERM_NAME[src.level]) {
    p = { level: src.level, sandbox: src.sandbox, read: src.level, from: src.from };
    other = true;
  }
  if (!p || !PERM_NAME[p.level]) return null;
  const text = !other && typeof p.text === "string" && p.text.trim() ? p.text.trim() : null;
  const was = PERM_NAME[p.read] ? p.read : p.level;
  const set = permSetting();
  const meant = PERM_NAME[set] ? set : set.startsWith("max:") && permRank(was) > permRank(set.slice(4)) ? set.slice(4) : was;
  const fell = !other && ((text && /the next stricter level/.test(text)) || (!text && permRank(p.level) < permRank(meant)));
  const flags = other ? null : Array.isArray(p.flags) ? p.flags.map(String) : [];
  return { level: p.level, sandbox: !!p.sandbox && p.level === "never", flags, text, was, meant, fell, other };
}
/** The line and the no-exact-match note.  The core's text as given; where
 * it gave none, words of our own.  `ctx`: {agent: the session's agent,
 * leaving: (its label) => the words for that session, on: the machine the
 * next agent starts on}. */
function permWords(x, agent, ctx = {}) {
  const label = AGENTS[agent] || agent || "The agent";
  const who = label + (ctx.on ? ` on ${ctx.on}` : "");
  const leaving = ctx.leaving ? ctx.leaving(ctx.agent ? AGENTS[ctx.agent] || ctx.agent : null) : "the session it continues";
  let line;
  if (x.text) line = x.text;
  else if (x.other) line = `${leaving[0].toUpperCase() + leaving.slice(1)} runs in ${permName(x.was, x.sandbox)}: ${who} starts in its own equivalent, or the next stricter level it has.`;
  else if (x.fell) line = `${who} starts in ${permName(x.level, x.sandbox)}, the next stricter level it has (${leaving} runs in ${PERM_NAME[x.was]}).`;
  else line = `${who} starts in ${permName(x.level, x.sandbox)}, like ${leaving}.`;
  return { line, fell: x.fell ? `No exact match: ${label} starts in the next stricter level it has.` : null };
}
/** A flag as a shell would need it written. */
const shellWord = (w) => (/^[\w@%+=:,./-]+$/.test(w) ? w : "'" + w.replace(/'/g, "'\\''") + "'");
/** The line, the no-exact-match note and the flags in small text; a
 * never-ask level in a caution box. */
function permPart(d, agent, ctx) {
  const x = agent ? permOf(d, agent) : null;
  if (!x) return null;
  const { line, fell } = permWords(x, agent, ctx);
  const label = AGENTS[agent] || agent;
  return h("div", { class: "perm " + x.level, "data-level": x.level },
    h("div", { class: "lead" }, x.level === "never" ? h("span", { class: "caution", text: "⚠ " }) : null, h("span", { class: "said", text: line })),
    fell ? h("div", { class: "warn small fell", text: fell }) : null,
    h("div", { class: "dim small flags" }, PERM_SAYS[x.level] + " ",
      x.flags === null ? `${label} gets its own flags for it.`
        : x.flags.length ? ["Flags: ", h("code", { text: x.flags.map(shellWord).join(" ") })] : `No flags: ${label}'s own default.`),
    ctx && ctx.later ? h("div", { class: "dim small", text: ctx.later }) : null);
}

/** Switch Agent: the dry run, then a dialog that asks how the agent goes
 * on: in a new session that reads the whole summary, or in its own latest
 * session here, which reads only what changed since it last worked here
 * (--resume).  Summary Only writes the summary and opens nothing. */
async function switchAgent(p, target) {
  const label = AGENTS[target] || target, name = base(p.real_path);
  note(p, null);
  // the dry run of both ways at once: a new session, and its own (--resume)
  const [fresh, ownPlan] = await busy(`checking ${name}…`, () => Promise.all([
    dryRun(["switch", p.real_path, "--to", target, "--json"]),
    dryRun(["switch", p.real_path, "--to", target, "--resume", "--json"])]));
  const plans = { new: fresh, resume: ownPlan };
  const why = problems(plans.new);
  if (why) return note(p, "Cannot switch now:\n\n" + why);
  const src = plans.new.source || {};
  const from = AGENTS[src.agent] || "the other agent";
  // the core finds the agent's own session in its store (the project list's
  // agents wait for the next sweep); without one it would start a new one
  const own = plans.resume.mode === "resume";
  let mode = "new";
  const s = sheet(`Continue “${name}” in ${label}`, "Continue in another agent", 600);
  const said = h("div", { class: "stack" });
  const go = h("button", { class: "primary", text: "Switch", onclick: () => { closeSheet(); startSwitch(p, target, mode, target !== "kimi" || kimiReads(plans[mode])); } });
  // what the chosen way would do: what stops it, what aht does instead
  // (fallback), and its warnings
  const pick = (m) => {
    mode = m;
    const x = plans[m], stop = problems(x);
    clear(said).append(stop ? h("p", { class: "warn small", style: "white-space:pre-wrap", text: "Not possible this way:\n\n" + stop })
      : permPart(x, x.target || target, { agent: (x.source || src).agent, leaving: (a) => `the ${a ? a + " " : ""}session you are leaving` }),
      !stop && (x.target || target) === "kimi" && !kimiReads(x) ? h("p", { class: "small kimi-opens", text: KIMI_OPENS }) : null,
      x.fallback ? h("p", { class: "warn small", text: x.fallback }) : null,
      (x.warnings || []).map((w) => h("p", { class: "warn small", text: "⚠ " + w })),
      x.start_line ? h("details", {}, h("summary", { class: "dim small", text: "What aht runs" }),
        h("pre", { style: "white-space:pre-wrap", text: x.start_line })) : null);
    go.disabled = !!stop;
  };
  const choice = (m, text, hint, off) => h("div", {},
    h("label", { class: "check" }, h("input", { type: "radio", name: "switch-mode", checked: m === mode, disabled: off,
      onchange: () => pick(m) }), text),
    h("div", { class: "dim small check-note", text: hint }));
  s.body.append(h("p", { text: `${label} continues the work of the latest ${from} session${src.title ? ` (“${src.title}”)` : ""}. aht writes a summary of where things stood into the project. The ${from} session stays as it is.` }),
    h("div", { class: "stack" }, h("strong", { text: `${label} goes on in` }),
      choice("new", "A new session", "It reads the whole summary first."),
      choice("resume", "Its own session", own ? `${label}'s latest session in this project goes on, and reads only what changed since it last worked here.`
        : `${label} has no session in this project yet.`, !own)),
    said,
    h("p", { class: "dim small", text: `Summary Only writes the summary into the project and opens nothing: start ${label} yourself and ask it to read the summary first.` }));
  s.foot.append(h("button", { text: "Summary Only", onclick: () => { closeSheet(); summaryOnly(p, target); } }),
    h("span", { class: "spacer" }), h("button", { text: "Cancel", onclick: closeSheet }), go);
  pick(mode);
}
async function startSwitch(p, target, mode, reads = true) {
  const label = AGENTS[target] || target, resume = mode === "resume";
  const a = await busy(!reads ? `opening ${label}…` : resume ? `${label} is catching up…` : `${label} is reading the summary…`,
    () => job(["switch", p.real_path, "--to", target, ...(resume ? ["--resume"] : []), "--apply", "--json"]));
  // fallback: its own session could not take the catch-up, so a new one did
  switched(p, a, label, (d) => (resume && !d.fallback ? `${label} went on in its own session; its window is open. What it read: ${d.brief || ""}`
    : `${d.fallback ? d.fallback + "\n\n" : ""}${label} took over; its window is open. The summary it read: ${d.brief || ""}`), "The switch did not go through");
}
/** What a switch or a Hand Back did, under the project; `done(answer)`
 * says it when it went through. */
function switched(p, a, label, done, notDone) {
  const d = a.json || {};
  // what aht printed holds the line to run by hand when no terminal opened
  const failed = problems(d) || (a.ok && d.applied ? null : ((a.out || "") + (a.err || "")).trim() || "aht gave no answer.");
  // Kimi below never-ask: its window opened without reading the summary;
  // the line to paste as its first message, with a Copy button
  const first = kimiFirst(d);
  const parts = first ? [firstPromptPart(first)] : undefined;
  // the summary is written before the terminal opens: only that step is left
  if (!(d.blockers || []).length && d.brief && /^No terminal window opened/.test(d.error || ""))
    note(p, `aht wrote the summary for ${label} (${d.brief}), but no terminal window opened. ${d.error.replace(/^No terminal window opened\.\s*/, "")}`, undefined, parts);
  else if (!failed && first) note(p, `${d.fallback ? d.fallback + "\n\n" : ""}${label}'s window is open. The summary is in the project: ${d.brief || ""}`, d.brief || undefined, parts);
  else note(p, failed ? `${notDone}:\n\n${failed}` : done(d));
  refresh();
}
/** Summary Only: the summary and the relay are written, nothing opens; the
 * user starts the agent when it suits them. */
async function summaryOnly(p, target) {
  const label = AGENTS[target] || target;
  const a = await busy("writing the summary…", () => run(["switch", p.real_path, "--to", target, "--brief-only", "--apply", "--json"]));
  const d = a.json || {};
  const failed = problems(d) || (a.ok && d.brief ? null : ((a.out || "") + (a.err || "")).trim() || "aht gave no answer.");
  if (failed) note(p, "The summary was not written:\n\n" + failed);
  else note(p, `The summary for ${label} is in the project; nothing was opened. Start ${label} in this folder and ask it to read this file first:\n\n${d.brief}`, d.brief);
  refresh();
}

/** The open relay on a project that is here (`relay`: {id, from_agent,
 * to_agent, since, open, machine, incoming, …}): another agent took the work
 * over on this machine and has not handed it back.  One that crosses
 * machines (`machine` set) goes back with Leave a Note, not here. */
const openRelay = (p) => (p.relay && p.relay.open !== false && !p.relay.machine && !p.relay.incoming && p.exists && !p.away ? p.relay : null);
function relayLine(p, r) {
  return h("div", { class: "row" },
    h("span", { text: `${AGENTS[r.to_agent] || r.to_agent} has had this project${r.since ? " since " + clock(r.since) : ""}, taken over from ${AGENTS[r.from_agent] || r.from_agent}.` }),
    h("button", { class: "small", text: "Hand Back…", disabled: !!p.handing, onclick: () => handBack(p) }));
}
/** Hand Back: the agent the newest open relay came from goes on in its own
 * session and reads only what changed since (`switch --back`).  When that
 * session is gone, the dry run says what aht does instead (fallback). */
async function handBack(p) {
  const r = openRelay(p) || {}, name = base(p.real_path);
  note(p, null);
  const [x, rl] = await busy(`checking ${name}…`, () => Promise.all([dryRun(["switch", p.real_path, "--back", "--json"]), J("relays", p.real_path, "--json")]));
  const why = problems(x);
  if (why) return note(p, "Cannot hand back now:\n\n" + why);
  const back = AGENTS[x.target] || x.target || AGENTS[r.from_agent] || r.from_agent || "the first agent";
  const now = AGENTS[r.to_agent] || r.to_agent || "the other agent";
  // the session it goes back to, as the relay recorded it
  const rec = (rl.relays || []).find((y) => y.id === r.id) || (rl.relays || []).find((y) => y.open) || {};
  const title = (rec.from || {}).title;
  let body = (x.fallback || `${back}'s own session${title ? ` (“${title}”)` : ""} goes on where it stopped, and reads only what ${now} did${r.since ? " since " + clock(r.since) : ""}.`)
    + ` The ${now} session stays as it is.`;
  if ((x.target || r.from_agent) === "kimi" && !kimiReads(x)) body += "\n\n" + KIMI_OPENS;
  for (const w of x.warnings || []) body += "\n\n⚠ " + w;
  const level = permPart(x, x.target || r.from_agent, { agent: r.to_agent, leaving: (a) => `the ${a ? a + " " : ""}session you are leaving` });
  if (!(await confirmIt(`Hand “${name}” back to ${back}?`, body, "Hand Back", level))) return;
  const a = await busy(`handing ${name} back to ${back}…`, () => job(["switch", p.real_path, "--back", "--apply", "--json"]));
  switched(p, a, back, (d) => (d.fallback ? `${d.fallback}\n\n${back}'s window is open. The summary it read: ${d.brief || ""}`
    : `${back} is back in its own session; its window is open. What ${now} did meanwhile: ${d.brief || ""}`), "Handing back did not go through");
}

// ---- across machines: Pick Up and Leave a Note ----------------------------------------
// They move the context only; git moves the files.  A Windows PC that aht
// cannot ask (no ssh server there, or an aht that does not answer) starts
// each exchange itself: at the PC, Pick Up from the Mac; before leaving it,
// Leave a Note on the Mac.

/** The machines Pick Up, Leave a Note and Bring Here can ask: Mac and
 * Linux ones.  A Windows PC starts these itself, also one that answers
 * (that takes Hand Over, Take Back, Watch, search and Check from here):
 * the core refuses them for every PC. */
const askable = () => (CAN_REACH() ? Object.entries((S.status.handover || {}).remotes || {})
  .filter(([, r]) => !!r && r.system !== "Windows").map(([n]) => n).sort() : []);
/** A machine set up here that is a Windows PC. */
const isPC = (name) => (remoteRow(name) || {}).system === "Windows";

/** The relay on a project's row that crosses machines (`relay.machine`: the
 * other one), or null: {kind, machine, remote, arrived, told, since,
 * from_agent, to_agent, back, agent, worked_from, worked_to, note_for}.
 * `arrived`: the work came here (a pickup made here, a note left here);
 * otherwise `machine` picked it up from here, and the work may go on there.
 * `remote`: that machine's name when it is set up here, so it can be asked.
 * `incoming` (on the receiving machine only) says more: its kind (pickup,
 * note, or back: the work handed back), who worked there and when, and the
 * session here a note is for.  A note that arrived opens nothing: it stays
 * on the row (open: false) until a session here heard of it (`told`). */
function crossing(p) {
  const r = p.relay;
  if (!r || !(r.machine || r.incoming) || !p.exists || p.away) return null;
  const inc = r.incoming && typeof r.incoming === "object" ? r.incoming : {};
  const kind = r.kind || inc.kind;
  const arrived = "arrived" in r ? !!r.arrived : !!r.incoming;
  if (!kind || (r.open === false && !(kind === "note" && arrived && !r.told))) return null;
  const nf = inc.note_for || r.note_for || null;
  return Object.assign({}, r, { kind, arrived, machine: r.machine || inc.machine || null, since: r.since || inc.at,
    back: inc.kind === "back", agent: inc.agent || r.from_agent, worked_from: inc.worked_from, worked_to: inc.worked_to,
    note_for: nf && typeof nf === "object" ? nf.session || null : nf,
    note_agent: (nf && typeof nf === "object" && nf.agent) || r.to_agent, note_title: nf && typeof nf === "object" ? nf.title : null,
    note_file: inc.brief ? ".aht/handover/" + base(inc.brief) : r.id ? `.aht/handover/relay-${r.id}.md` : null });
}

/** The pickup from another machine that is open here: {machine, remote,
 * relay, at, agent, session} (agent and session: the one there the work
 * came from), or null.  A newer core names it in the row's `pickup_from`
 * (null: none), also when a newer relay here (a switch to another agent,
 * say) is the row's `relay`; an older one only through that relay. */
function pickedUp(p) {
  if (!p.exists || p.away) return null;
  if ("pickup_from" in p) {
    const f = p.pickup_from;
    return f && typeof f === "object" && (f.machine || f.remote) ? f : null;
  }
  const x = crossing(p);
  return x && x.arrived && x.kind === "pickup" && !x.back
    ? { machine: x.machine, remote: x.remote, relay: x.id, at: x.since, agent: x.from_agent, session: null } : null;
}
/** "Picked up from M at T: X's session there", with Hand Back to M (a note
 * for that session) when M is set up here and can be asked. */
function pickupLine(p, f) {
  const who = f.remote || f.machine || "another machine", at = f.at ? " at " + clock(f.at) : "";
  const fa = AGENTS[f.agent] || f.agent;
  // the agent it went on in here, while the pickup is still the row's relay
  const to = p.relay && p.relay.id === f.relay ? p.relay.to_agent : null, ta = AGENTS[to] || to;
  const can = !!f.remote && askable().includes(f.remote);
  return h("div", { class: "row" },
    h("span", { text: `Picked up from ${who}${at}${fa ? `: ${fa}'s session there` : ""}${ta && ta !== fa ? `, going on in ${ta}` : ""}.` }),
    can ? h("button", { class: "small", text: `Hand Back to ${f.remote}…`, disabled: !!p.handing, onclick: () => leaveNote(p, f.remote) }) : null);
}

/** What the session a hand-back note is for does with it when it is
 * continued (`where`: " on box", or "" for here): Claude Code reads it by
 * itself, as aht's hook gives it to the session (`hook`: the hook is set
 * up there).  No other agent has that hook: it is asked to read the note
 * (`file`) first. */
function noteReads(agent, where, file, hook = true) {
  const f = file || "the note";
  if (!agent) return `When you continue that session${where}, Claude Code reads it by itself; another agent does not: ask it to read ${f} first.`;
  if (agent === "claude" && hook) return `Claude Code reads it by itself when you continue that session${where}.`;
  return `${AGENTS[agent] || agent} does not read it by itself${agent === "claude" ? " (aht's hook is off)" : ""}: when you continue that session${where}, ask it to read ${f} first.`;
}
/** …and a note for no session in particular: aht's hook tells a Claude
 * Code session that starts there of it, once. */
function noteTold(where, file, hook = true) {
  const f = file || "the note";
  return hook ? `A Claude Code session that starts ${where} is told of it; with another agent, ask it to read ${f}.`
    : `aht's hook is off, so no session is told of it: ask the agent to read ${f}.`;
}

/** The line under a project whose work crossed machines; a note that
 * arrived is a banner of its own.  Work picked up here from another
 * machine has its own line (pickupLine). */
function crossingLine(p, x) {
  const who = x.remote || x.machine || "another machine", at = x.since ? " at " + clock(x.since) : "";
  const ta = AGENTS[x.to_agent] || x.to_agent;
  const can = askable().includes(x.remote);
  if (x.kind === "note" && x.arrived) return noteBanner(p, x);
  if (x.kind !== "pickup") return null;
  if (x.arrived && x.back) return h("div", { class: "dim small", text: `The work came back from ${who}${at}.` });
  if (x.arrived) return null;
  return h("div", { class: "row" },
    h("span", { text: `Picked up on ${who}${at}${ta ? ` (${ta})` : ""}: the work may go on there.` }),
    can ? h("button", { class: "small", text: `Pick Up from ${who}…`, disabled: !!p.handing, onclick: () => pickUp(p, who) })
      : h("span", { class: "dim small", text: `When it comes back, ${who} leaves a note here.` }));
}
/** The banner when another machine left a note here, or handed the work
 * back (`back`): who worked there and when, which session here it is for;
 * [Read the Note…] and, for a session here (`note_for`), [Continue That
 * Session]: Claude Code's reads the note as it opens (aht's hook), another
 * agent's is asked to. */
function noteBanner(p, x) {
  const who = x.remote || x.machine || "another machine", by = AGENTS[x.agent] || x.agent;
  const own = x.note_for ? AGENTS[x.note_agent] || x.note_agent || "Claude Code" : null;
  const hook = S.status.hook_installed !== false;
  const worked = by && x.worked_from && x.worked_to ? `${by} worked on it there ${clock(x.worked_from)}–${clock(x.worked_to)}.`
    : `Left${x.since ? " at " + clock(x.since) : ""}${by ? `, after ${by} worked on it there` : ""}.`;
  return h("div", { class: "callout info row" },
    h("div", { class: "grow" }, h("strong", { text: x.back ? `${who} handed the work back` : `A note from ${who}` }),
      h("div", { class: "small", text: `${worked} `
        + (own ? `The note is for ${own}'s session${x.note_title ? ` “${x.note_title}”` : ""} here. ${noteReads(x.note_agent || "claude", "", x.note_file, hook)}`
          : noteTold("here", x.note_file, hook)) + ` Pull with git first if the files changed on ${who}.` })),
    h("button", { class: "small", text: "Read the Note…", onclick: () => readNote(p, x) }),
    own ? h("button", { class: "small primary", text: "Continue That Session",
      onclick: () => resume([p.real_path, "--session", x.note_for, "--agent", x.note_agent || "claude"]) }) : null,
    helpBtn("Pick up on another machine"));
}
async function readNote(p, x) {
  const d = await busy("reading the note…", () => J("relays", p.real_path, "--show", x.id, "--json"));
  const file = (d.relay || {}).brief;
  textSheet(`A note from ${x.remote || x.machine || "another machine"}`, d.text || "The note could not be read.", "Pick up on another machine",
    file ? h("button", { text: ON_WINDOWS() ? "Show in Explorer" : "Show in Files", onclick: () => post("/api/reveal", { path: parent(file) }) }) : null);
}

/** The project row's Machines menu.  With work picked up from M open here,
 * what goes to M is a hand-back (Leave a Note does the same then). */
function machinesMenu(p, names, held) {
  const f = pickedUp(p);
  const back = f && f.remote && names.includes(f.remote) ? f.remote : null;
  const items = back ? [[`Hand Back to ${back}…`, () => leaveNote(p, back)], "-"] : [];
  for (const n of names) items.push([`Pick Up from ${n}…`, () => pickUp(p, n)]);
  const notes = names.filter((n) => n !== back);
  if (notes.length) items.push("-", ...notes.map((n) => [`Leave a Note on ${n}…`, () => leaveNote(p, n)]));
  return menu("Machines", items, { disabled: held });
}

/** How the folder there was found (`match.how`), in the core's words. */
const FOUND = { id: "found by its project id", origin: "found by its git origin", path: "found at the same path",
  home: "found at the same place in the home folder", there: "as you named it" };
const SAME = { origin: "with the same git origin", path: "at the same path", home: "at the same place in the home folder" };
/** Where the project is on the other machine (`match`: {path, how,
 * candidates}) and here; why not, when it cannot go ahead.  `error`: the
 * machine could not be asked; two candidates found the same way block; none
 * found asks for its path there.  `on.choose(path)` looks again at a folder
 * there, `on.retry()` asks again, `on.change()` picks another folder here. */
function matchPart(d, machine, p, on) {
  const m = d.match || {}, why = problems(d);
  const cands = (m.candidates || []).filter((c) => c && (!m.how || c.how === m.how));
  if (d.error || !d.match) {                // not asked, or no answer
    return h("div", { class: "callout" }, h("strong", { text: `aht could not ask ${machine}` }),
      h("div", { class: "small", style: "white-space:pre-wrap" }, inline(why || "aht gave no answer.")),
      h("div", { class: "row", style: "margin-top:6px" }, h("button", { class: "small", text: "Try Again", onclick: on.retry })));
  }
  if (m.path) {
    return [h("div", { class: "facts" },
      h("span", { class: "dim", text: `On ${machine}` }),
      h("span", {}, h("span", { class: "mono", text: m.path }), " ", h("span", { class: "dim small", text: FOUND[m.how] || m.how || "" })),
      h("span", { class: "dim", text: "Here" }),
      h("span", {}, h("span", { class: "mono", text: tilde(p.real_path) }),
        on.change ? [" ", h("button", { class: "small", text: "Another Folder…", onclick: on.change })] : null)),
    SAME[m.how] ? h("p", { class: "warn small", text: `aht found no folder on ${machine} with this project's id, only one ${SAME[m.how]}: check that it is the same project.` }) : null,
    why ? h("div", { class: "callout" }, h("strong", { text: "Not possible now" }), h("div", { class: "small", style: "white-space:pre-wrap", text: why })) : null];
  }
  if (cands.length > 1) {
    return h("div", { class: "callout" }, h("strong", { text: `${plural(cands.length, "folder")} on ${machine} could be this project` }),
      h("div", { class: "small", text: "Choose the one to use; aht did not find this project's id in either." }),
      cands.map((c) => h("div", { class: "row cand" }, h("span", { class: "mono grow", text: c.path }),
        c.how ? h("span", { class: "dim small", text: FOUND[c.how] || c.how }) : null,
        h("button", { class: "small", text: "This One", onclick: () => on.choose(c.path) }))));
  }
  // asked, and no copy there: its folder, typed
  const input = h("input", { type: "text", placeholder: `its full path on ${machine}`, style: "flex:1;min-width:240px" });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && input.value.trim()) on.choose(input.value.trim()); });
  return h("div", { class: "callout" }, h("strong", { text: `aht found no copy of “${base(p.real_path)}” on ${machine}` }),
    why ? h("div", { class: "small", style: "white-space:pre-wrap", text: why }) : null,
    h("div", { class: "row", style: "margin-top:6px" }, input,
      h("button", { class: "small", text: "Look There", onclick: () => { if (input.value.trim()) on.choose(input.value.trim()); } })));
}
/** The latest sessions in the folder there (`sessions`, or the source's):
 * the one picked up marked, the others a click away. */
function sessionsThere(d, machine, pick) {
  const src = d.source || {}, list = d.sessions || src.sessions || [];
  const cur = src.session || src.id;
  const facts = (x) => [AGENTS[x.agent] || x.agent, x.updated || x.last_t ? "last active " + ago(x.updated || x.last_t) : null].filter(Boolean).join(" · ");
  if (!list.length) {
    return cur ? h("p", { class: "small" }, `From ${machine}: `, h("strong", { text: src.title || "(no title)" }),
      h("span", { class: "dim", text: " · " + facts(src) })) : null;
  }
  return [h("h3", { text: `Latest sessions on ${machine}` }), h("div", { class: "sessions" }, list.slice(0, 6).map((x) => {
    const id = x.id || x.session, on = id === cur;
    const state = x.state && x.state !== "closed" ? x.state : x.working ? "working" : x.open ? "open" : "";
    return h("div", { class: "s" + (on ? " on" : "") },
      h("div", { class: "grow" }, h("div", { class: "row" }, h("strong", { class: "ellipsis", text: x.title || "(no title)" }),
        state ? h("span", { class: "badge " + (state === "working" ? "working" : state === "waiting" ? "waiting" : ""),
          text: state === "open" ? "open there" : state }) : null),
      h("div", { class: "dim small", text: facts(x) })),
      on ? h("span", { class: "dim small", text: "picked up" })
        : h("button", { class: "small", text: "Pick Up This One", onclick: () => pick(id) }));
  }))];
}
/** git on both sides (`git`: {here, there, advice}): the summary carries no
 * files, so what is not committed or pushed comes first.  The core's advice
 * says it in its own words; without one, each side's state does. */
function gitBox(g, machine) {
  if (!g || typeof g !== "object") return null;
  const facts = (x) => [x.branch ? `branch ${x.branch}` : "no branch", x.head ? `at ${x.head}` : null,
    x.ahead ? `${plural(x.ahead, "commit")} not pushed` : null, x.behind ? `${x.behind} behind ${x.upstream || "its upstream"}` : null,
    x.dirty ? `${plural(x.dirty, "file")} not committed` : null].filter(Boolean).join(", ");
  const side = (x, where) => (x === undefined ? null : h("div", { class: "small" }, h("span", { class: "dim", text: where + ": " }), x ? facts(x) : "no git repository"));
  const say = g.advice || g.warning || g.say || null;
  const todo = !!say || [g.there, g.here].some((x) => x && (x.dirty || x.ahead));
  return h("div", { class: todo ? "callout git" : "box git" }, todo ? h("strong", { text: "The files move with git, not with the summary" }) : null,
    say ? h("div", { class: "small", text: say }) : [side(g.there, `On ${machine}`), side(g.here, "Here")]);
}
/** The summary in a Pick Up or Leave a Note answer: its text (the dry run
 * shows it), its file (once written) and its kind (full, catchup or
 * full+catchup). */
function briefOf(d) {
  const b = d.brief, kind = d.brief_kind || (b && b.kind) || null;
  if (b && typeof b === "object") return { text: b.text || null, file: b.path || null, kind };
  if (typeof b === "string" && /\n/.test(b)) return { text: b, file: null, kind };
  return { text: null, file: typeof b === "string" ? b : null, kind };
}
/** Work coming back (`back_of`: the relay it went out with): when it left,
 * read from that relay's id (its date and time). */
const backMode = (d) => !!d.back_of || d.mode === "back";
function relayTime(id) {
  const m = /^(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)/.exec(id || "");
  return m ? new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime() / 1000 : null;
}
/** What opening `agent` with the summary costs: it reads it as its first
 * turn (tokens), unless Claude Code's own session comes back (`session`:
 * the one here that goes on), which aht's hook tells as it opens. */
function tokenLine(agent, d) {
  const label = AGENTS[agent] || agent, own = agent === d.target && !!d.session;
  if (own && agent === "claude" && S.status.hook_installed !== false) {
    return "Claude Code's own session goes on: aht's hook tells it what happened meanwhile, so nothing runs until you type.";
  }
  if (agent === "kimi" && !kimiReads(d)) return KIMI_OPENS + " Reading it is Kimi's first turn: it uses tokens.";
  if (agent === "kimi") return "Kimi reads the summary in a first run of its own, before its window opens or its line is copied: that turn uses tokens.";
  if (own) return `${label}'s own session reads what happened meanwhile as its next turn: it uses tokens.`;
  return `Reading the summary is ${label}'s first turn: it uses tokens.`;
}
const copyText = (t) => navigator.clipboard.writeText(t).then(() => toast("Copied."), () => toast("It could not be copied: select the line and copy it."));

// ---- Kimi below never-ask ---------------------------------------------------------------
// Kimi's run of its own that reads the summary first (`-p`) always runs in
// never-ask, so the core uses it only at never-ask (`kimi_reads: true`).
// Below it, Switch, Hand Back and Pick Up → Open in Kimi open Kimi's own
// session without that run (`kimi_reads: false`) and give `first_prompt`:
// the one line that asks it to read the summary, for the user to paste.
const KIMI_OPENS = "Kimi opens without reading the summary: its run that reads it first works only in never-ask mode, so you paste the first message aht shows you.";
/** Whether Kimi reads the summary in a run of its own first: the core's
 * `kimi_reads` (when it speaks of Kimi), else Kimi's level from the dry run
 * (never-ask: it does); an older core that says neither: it does. */
function kimiReads(d) {
  if (!d || typeof d !== "object") return true;
  const own = d.perm && typeof d.perm === "object" ? d.perm.agent || d.target : d.target;
  if (typeof d.kimi_reads === "boolean" && (!own || own === "kimi")) return d.kimi_reads;
  const x = permOf(d, "kimi");
  return x ? x.level === "never" : true;
}
/** An answer that opened (or would open) Kimi without its reading run, and
 * the line to paste as its first message; null otherwise. */
const kimiFirst = (d) => (d && d.kimi_reads === false && typeof d.first_prompt === "string" && d.first_prompt.trim() ? d.first_prompt.trim() : null);
/** The first message to paste, with its Copy button. */
const firstPromptPart = (line) => h("div", { class: "callout info first-prompt" },
  h("strong", { text: "Kimi opens without reading the summary. Paste this as your first message:" }),
  h("div", { class: "row top" }, h("pre", { class: "grow", style: "white-space:pre-wrap;margin:4px 0", text: line }),
    h("button", { class: "small", text: "Copy", onclick: () => copyText(line) })));

/** Pick Up from M: what was last done in this project on M, as a summary
 * made and masked there (`pickup --json`, a dry run): the folder there and
 * how it was found, the latest sessions there, git on both sides, and the
 * summary.  [Open in X] writes it here and starts X with it (one turn:
 * tokens); [Copy the Start Line] writes it and copies the line, so nothing
 * runs; [Done] closes and writes nothing.  `o`: {session, there} to start
 * from (a search hit), `change`: another folder here. */
async function pickUp(p, machine, o = {}) {
  const name = base(p.real_path);
  note(p, null);
  const s = sheet(`Pick up “${name}” from ${machine}`, "Pick up on another machine", 860);
  const agents = SWITCH_TO.filter((a) => (S.status.agent_clis || {})[a]);
  const st = { session: o.session || null, there: o.there || null, agent: null, d: null, done: null, failed: null, working: null };
  // the session and the folder there; on --apply also the folder that was
  // shown, when it was not found by its project id
  const opts = (apply) => {
    const m = (st.d && st.d.match) || {};
    const there = st.there || (apply && m.path && m.how !== "id" ? m.path : null);
    return [...(there ? ["--there", there] : []), ...(st.session ? ["--session", st.session] : [])];
  };
  const planned = () => (st.d ? st.d.target || st.d.agent : null);
  const look = async () => {
    st.d = null; st.failed = null; paint();
    const d = await dryRun(["pickup", p.real_path, "--from", machine, ...opts(false), "--json"]);
    if (!s.body.isConnected) return;                // closed meanwhile
    st.d = d;
    if (!agents.includes(st.agent)) st.agent = [d.target, d.agent, (d.source || {}).agent, "claude"].find((a) => agents.includes(a)) || agents[0] || null;
    paint();
  };
  const copyLine = async () => {
    if (st.done) return copyText(st.done.line);
    const label = AGENTS[st.agent] || st.agent;
    st.working = st.agent === "kimi" && kimiReads(st.d) ? "Kimi is reading the summary…" : "writing the summary…"; st.failed = null; paint();
    // --open X with --no-window: the summary here and its copy there, the
    // line that starts X with it, and no terminal (Kimi reads it first, in a
    // run of its own); --agent would pick the session there, not X
    const a = await job(["pickup", p.real_path, "--from", machine, ...opts(true), "--open", st.agent, "--apply", "--no-window", "--json"]);
    st.working = null;
    const d = a.json || {};
    const failed = problems(d) || (a.ok && d.applied ? null : ((a.out || "") + (a.err || "")).trim() || "aht gave no answer.");
    if (failed) {
      st.failed = failed;
      return s.body.isConnected ? paint() : note(p, "The summary was not written:\n\n" + failed);
    }
    const line = d.command_line || d.start_line || "";
    // Kimi below never-ask: it starts without reading the summary; the line
    // to paste as its first message
    st.done = { line, file: briefOf(d).file, copied: false, first: kimiFirst(d) };
    note(p, `Picked up from ${machine}; nothing was opened.` + (line ? ` Start ${label} in a terminal with:\n\n${line}` : ""), st.done.file,
      st.done.first ? [firstPromptPart(st.done.first)] : undefined);
    refresh();
    if (!s.body.isConnected) return;
    if (line) st.done.copied = await navigator.clipboard.writeText(line).then(() => true, () => false);
    paint();
    if (st.done.copied) toast("Copied.");
  };
  const openIn = async () => {
    const agent = st.agent, label = AGENTS[agent] || agent, back = backMode(st.d) && agent === planned() && !!st.d.session;
    const extra = opts(true);
    closeSheet();
    const a = await busy(agent === "kimi" && kimiReads(st.d) ? "Kimi is reading the summary…" : `opening ${label}…`,
      () => job(["pickup", p.real_path, "--from", machine, ...extra, "--open", agent, "--apply", "--json"]));
    const d = a.json || {};
    switched(p, Object.assign({}, a, { json: Object.assign({}, d, { brief: briefOf(d).file }) }), label, (x) => (back
      ? `Back from ${machine}: ${label}'s own session goes on; its window is open. What happened on ${machine} meanwhile: ${x.brief || ""}`
      : `Picked up from ${machine}: ${label}'s window is open. The summary it read: ${x.brief || ""}`), "Picking up did not go through");
  };
  const paint = () => {
    const b = clear(s.body), f = clear(s.foot), d = st.d;
    const done = h("button", { text: "Done", onclick: () => { closeSheet(); if (st.done) refresh(); } });
    if (!d) {
      b.append(h("p", { class: "dim" }, h("span", { class: "spin" }), `Asking ${machine}…`));
      f.append(h("span", { class: "spacer" }), done);
      return;
    }
    const m = d.match || {}, ok = !problems(d) && !!m.path, back = backMode(d);
    const label = () => AGENTS[st.agent] || st.agent || "an agent";
    const wrap = h("div", { class: "stack" });
    b.append(wrap);
    if (st.done) {
      wrap.append(h("div", { class: "callout info" }, h("strong", { text: "The summary is in the project; nothing was opened" }),
        st.done.file ? h("div", { class: "small mono", text: st.done.file }) : null,
        st.done.line ? [h("div", { class: "small", text: st.done.copied ? `The line that starts ${label()} with it is copied: paste it into a terminal.`
          : `To start ${label()} with it, run this line in a terminal:` }),
        h("div", { class: "row top" }, h("pre", { class: "grow", style: "white-space:pre-wrap;margin:4px 0", text: st.done.line }),
          h("button", { class: "small", text: "Copy", onclick: () => copyText(st.done.line) }))] : null),
      st.done.first ? firstPromptPart(st.done.first) : null);
    }
    if (st.failed) wrap.append(h("p", { class: "warn small", style: "white-space:pre-wrap", text: "The summary was not written:\n\n" + st.failed }));
    wrap.append(matchPart(d, machine, p, { choose: (x) => { st.there = x; look(); }, retry: look, change: o.change }));
    if (m.path) wrap.append(sessionsThere(d, machine, (id) => { st.session = id; look(); }));
    if (back && ok) {
      const t = AGENTS[planned()] || planned() || "The agent", left = relayTime(d.back_of);
      const title = d.note_for && typeof d.note_for === "object" && d.note_for.title;
      wrap.append(h("p", { text: `This work went to ${machine}${left ? " at " + clock(left) : ""} and comes back now: `
        + (d.session ? `${t}'s own session here${title ? ` (“${title}”)` : ""} goes on, and reads only what happened on ${machine} since.`
          : `a new ${t} session reads the summary and what happened on ${machine} since.`) }));
    }
    if (d.fallback) wrap.append(h("p", { class: "warn small", text: d.fallback }));
    // git's warning is in the box, not again among the warnings
    wrap.append(gitBox(d.git, machine), (d.warnings || []).filter((w) => w !== (d.git || {}).warning).map((w) => h("p", { class: "warn small", text: "⚠ " + w })));
    const bf = briefOf(d);
    if (bf.text) {
      wrap.append(h("div", {}, h("h3", { text: bf.kind === "catchup" ? `What happened on ${machine} since`
        : bf.kind === "full+catchup" ? `Where things stood on ${machine}, and what happened since` : `Where things stood on ${machine}` }),
      h("div", { class: "brief" }, md(bf.text, true))));
    }
    const tok = h("span", { class: "dim small" });
    // the level the agent chosen starts in, like the session there
    const level = h("div");
    // what Copy the Start Line does for the agent chosen
    const cp = st.done ? null : h("div", { class: "dim small" });
    const go = h("button", { class: "primary", disabled: !ok || !st.agent || !!st.done || !!st.working, onclick: openIn });
    const runs = d.start_line ? h("details", {}, h("summary", { class: "dim small", text: "What aht runs" }), h("pre", { style: "white-space:pre-wrap", text: d.start_line })) : null;
    const said = () => {
      go.textContent = st.agent ? `Open in ${label()}` : "Open in …";
      tok.textContent = st.agent ? tokenLine(st.agent, d) : "";
      clear(level).append(permPart(d, st.agent, { agent: (d.source || {}).agent, leaving: (a) => `the ${a ? a + " " : ""}session on ${machine}` }));
      level.hidden = !level.firstChild;
      if (cp) cp.textContent = `Copy the Start Line writes the summary here and a copy of it on ${machine}, and copies the line that starts ${label()} with it: `
        + (st.agent === "kimi" && kimiReads(st.d) ? "Kimi reads the summary in a run of its own first (that turn uses tokens), then nothing runs until you paste the line into a terminal."
          : st.agent === "kimi" ? "nothing runs until you paste it into a terminal; then paste the first message aht shows you into Kimi."
            : "nothing runs until you paste it into a terminal.") + " Done closes this and writes nothing.";
      if (runs) runs.hidden = st.agent !== planned();
    };
    if (ok && agents.length) {
      wrap.append(h("div", { class: "openin" }, h("div", { class: "row" }, h("strong", { text: "Open in" }),
        h("select", { disabled: !!st.done, onchange: (e) => { st.agent = e.target.value; said(); } },
          agents.map((a) => h("option", { value: a, text: AGENTS[a] || a, selected: a === st.agent }))), tok),
      level, cp, runs));
    } else if (ok) wrap.append(h("p", { class: "dim small", text: "No agent CLI is installed on this computer to open it in." }));
    said();
    f.append(h("button", { text: "Copy the Start Line", disabled: !st.done && (!ok || !st.agent || !!st.working), onclick: copyLine }),
      st.working ? h("span", { class: "dim small" }, h("span", { class: "spin" }), st.working) : null,
      h("span", { class: "spacer" }), done, go);
  };
  paint();
  look();
}

/** Leave a Note on M: a summary of the work here goes into the project's
 * folder on M (`leave-note --json`; a dry run first).  When this folder
 * picked the work up from M, it is a hand-back: a catch-up for the session
 * there that the work came from (`note_for`).  Nothing runs there, and no
 * agent reads anything now: no tokens. */
async function leaveNote(p, machine) {
  const name = base(p.real_path);
  note(p, null);
  const s = sheet(`Leave a note for “${name}” on ${machine}`, "Pick up on another machine", 820);
  const st = { there: null, d: null, failed: null, working: null };
  const isBack = (d) => backMode(d) || !!d.note_for || d.mode === "catchup";
  // the session there the work came from: the core's note_for, else the
  // pickup open on this project's row
  const x = pickedUp(p) || {};
  const origin = (d) => (d.note_for && typeof d.note_for === "object" ? d.note_for
    : { agent: x.agent || null, title: null });
  const opts = (apply) => {
    const m = (st.d && st.d.match) || {};
    const there = st.there || (apply && m.path && m.how !== "id" ? m.path : null);
    return there ? ["--there", there] : [];
  };
  const look = async () => {
    st.d = null; st.failed = null; paint();
    const d = await dryRun(["leave-note", p.real_path, "--on", machine, ...opts(false), "--json"]);
    if (!s.body.isConnected) return;
    st.d = d;
    paint();
  };
  const leave = async () => {
    const back = isBack(st.d), extra = opts(true), there = (st.d.match || {}).path;
    st.working = back ? "handing back…" : "leaving the note…"; st.failed = null; paint();
    const a = await job(["leave-note", p.real_path, "--on", machine, ...extra, "--apply", "--json"]);
    st.working = null;
    const d = a.json || {};
    const failed = problems(d) || (a.ok && d.applied ? null : ((a.out || "") + (a.err || "")).trim() || "aht gave no answer.");
    if (failed && s.body.isConnected) { st.failed = failed; return paint(); }
    if (s.body.isConnected) closeSheet();
    // where it is there, as the core says it (`left`: the files written there)
    const file = d.relay && there ? `${there.replace(/\/+$/, "")}/.aht/handover/relay-${d.relay}.md` : (d.left || [])[0] || there;
    const git = (d.git || st.d.git || {}).warning;
    const rel = d.relay ? `.aht/handover/relay-${d.relay}.md` : null;
    note(p, failed ? `The note was not left on ${machine}:\n\n${failed}`
      : (back ? `Handed back to ${machine}: the note is for the session there that the work came from. ${noteReads(origin(d.note_for ? d : st.d).agent, " on " + machine, rel)}`
        : `The note is on ${machine}. ${noteTold("there", rel)}`)
        + (file ? `\n\n${file}` : "") + (git ? `\n\n${git}` : ""));
    refresh();
  };
  const paint = () => {
    const b = clear(s.body), f = clear(s.foot), d = st.d;
    const cancel = h("button", { text: "Cancel", onclick: closeSheet });
    if (!d) {
      b.append(h("p", { class: "dim" }, h("span", { class: "spin" }), `Asking ${machine}…`));
      f.append(h("span", { class: "spacer" }), cancel);
      return;
    }
    const m = d.match || {}, ok = !problems(d) && !!m.path, back = isBack(d);
    s.head.querySelector("h1").textContent = back ? `Hand “${name}” back to ${machine}` : `Leave a note for “${name}” on ${machine}`;
    const o = origin(d), t = AGENTS[o.agent] || o.agent, came = relayTime(d.back_of);
    const wrap = h("div", { class: "stack" });
    b.append(wrap);
    if (st.failed) wrap.append(h("p", { class: "warn small", style: "white-space:pre-wrap", text: "The note was not left:\n\n" + st.failed }));
    wrap.append(matchPart(d, machine, p, { choose: (x) => { st.there = x; look(); }, retry: look }));
    if (ok) {
      wrap.append(h("p", { text: back
        ? `The work came here from ${t ? `${t}'s session` : "a session"} on ${machine}${o.title ? ` (“${o.title}”)` : ""}. The note is for that session, with what happened here${came ? " since " + clock(came) : ""}. `
          + noteReads(o.agent, " on " + machine, "the note (in the project's .aht/handover folder there)")
        : `The note goes into the project's folder on ${machine}: where things stood here, the latest exchanges, the open to-dos and git's state. ` + noteTold("there") }));
    }
    wrap.append(gitBox(d.git, machine), (d.warnings || []).filter((w) => w !== (d.git || {}).warning).map((w) => h("p", { class: "warn small", text: "⚠ " + w })));
    const bf = briefOf(d);
    if (bf.text) wrap.append(h("div", {}, h("h3", { text: back ? `The note for ${machine}: what happened here since` : "The note" }), h("div", { class: "brief" }, md(bf.text, true))));
    f.append(h("span", { class: "dim small", text: `Nothing runs on ${machine}, and no tokens are used.` }),
      st.working ? h("span", { class: "dim small" }, h("span", { class: "spin" }), st.working) : null,
      h("span", { class: "spacer" }), cancel,
      h("button", { class: "primary", text: back ? "Hand Back" : "Leave the Note", disabled: !ok || !!st.working, onclick: leave }));
  };
  paint();
  look();
}

/** Continue Here… on a search hit from another machine: Pick Up from that
 * machine, with that session and its folder there, into the project's
 * folder here (the one tracked here by the same name, or one chosen). */
async function continueFromThere(r) {
  const name = base(r.project);
  const choose = () => pickFolder(`Where is “${name}” on this computer? Pick Up brings the work from ${r.machine} into its folder here.`);
  const same = S.projects.filter((p) => p.exists && !p.away && base(p.real_path).toLowerCase() === name.toLowerCase());
  const path = same.length === 1 ? same[0].real_path : await choose();
  if (!path) return;
  const go = (x) => pickUp(S.projects.find((p) => p.real_path === x) || { real_path: x, exists: true }, r.machine,
    { session: r.session, there: r.project, change: async () => { const y = await choose(); if (y) go(y); } });
  go(path);
}

// Show Sessions: every session, branches under the one they came from
async function openSessionList(p) {
  const d = await busy("reading the sessions…", () => J("sessions", p.real_path, "--json"));
  const items = d.sessions || [];
  const s = sheet(`Sessions: ${base(p.real_path)}`, "A project's sessions", 860);
  s.body.append(h("p", { class: "dim", text: "Every session in this folder, the latest work first. A branch (/branch in Claude Code) sits under the session it came from, with the time it branched. Continue opens a session in a new terminal window." }));
  if (p.away) s.body.append(h("p", { class: "warn", text: `This project is handed over to ${p.away}: take it back before you continue a session here.` }));
  else if (p.handing) s.body.append(h("p", { class: "warn", text: `The handover to ${handing(p).to} is unfinished: check it, or release the project, before you continue a session here.` }));
  const filter = h("input", { type: "search", placeholder: "Filter by title", style: "margin-bottom:6px" });
  const box = h("div", { class: "sessions" });
  const drawList = () => {
    const q = filter.value.trim().toLowerCase();
    clear(box);
    for (const it of items.filter((x) => !q || (x.title || "").toLowerCase().includes(q) || x.id.startsWith(q))) {
      const bits = [];
      if (it.agent !== "claude") bits.push(AGENTS[it.agent] || it.agent);
      bits.push(it.branched ? "branched " + when(it.branched) : it.started ? "started " + when(it.started) : null);
      bits.push("last active " + when(it.updated));
      if (it.parent_gone) bits.push("branched from a session that is gone");
      box.append(h("div", { class: "s" },
        h("span", { style: `width:${Math.max(0, it.depth - 1) * 24 + (it.depth ? 4 : 0)}px;flex:none` }),
        it.depth ? h("span", { class: "branch", text: "⑂", title: "A branch (/branch in Claude Code)" }) : null,
        h("div", { class: "grow" }, h("div", { class: "row" }, h("strong", { class: "ellipsis", text: it.title || "(no title)" }),
          it.open ? h("span", { class: "okc small", text: "open now" }) : null),
          h("div", { class: "dim small", text: bits.filter(Boolean).join(" · ") })),
        h("span", { class: "dim mono", text: it.id.slice(0, 8), title: "Session id: " + it.id }),
        it.open ? h("span", { class: "dim small", text: "open in its terminal" })
          : h("button", { text: "Continue", disabled: !!p.away || !!p.handing,
            onclick: () => resume([p.real_path, "--session", it.id, "--agent", it.agent]) })));
    }
    if (!items.length) box.append(h("p", { class: "dim", text: "No sessions in this folder yet." }));
  };
  filter.addEventListener("input", drawList);
  if (items.length > 6) s.body.append(filter);
  s.body.append(box);
  drawList();
  const n = items.filter((x) => x.branched).length;
  s.foot.append(h("span", { class: "dim small", text: plural(items.length, "session") + (n ? `, ${n} of them branches` : "") }),
    h("span", { class: "spacer" }), h("button", { text: "Close", class: "primary", onclick: closeSheet }));
}

function textSheet(title, text, topic, extra) {
  const s = sheet(title, topic, 820);
  s.body.append(md(text, true));
  s.foot.append(h("button", { text: "Copy", onclick: () => navigator.clipboard.writeText(text).then(() => toast("Copied.")) }),
    extra || null, h("span", { class: "spacer" }), h("button", { text: "Close", class: "primary", onclick: closeSheet }));
}
async function openJournal(p) {
  const d = await busy("writing the journal…", () => J("journal", p.real_path, "--json"));
  textSheet(`Journal: ${base(p.real_path)}`, d.markdown || "The journal could not be written.", "Project journal",
    h("button", { text: "Save in the Project and Open", onclick: async () => {
      const w = await J("journal", p.real_path, "--write", "--json");
      if (w.file) { post("/api/reveal", { path: w.file }); toast("Saved: " + w.file); }
    } }));
}
async function openStatement(p) {
  const d = await busy("writing the statement…", () => J("report", "--project", p.real_path, "--statement", "--json"));
  textSheet(`AI-use statement: ${base(p.real_path)}`, (d.statement || "") +
    "\n\n_A draft from the agents' histories: check the numbers and the tasks before you use it._", "Reports and an AI-use statement");
}
async function share(p) {
  const name = base(p.real_path);
  const ans = await ask("Share the latest session", `aht writes a page of ${name}'s latest session into the project folder (${name} session.html) and shows it. Keys and passwords aht recognises are masked; e-mail addresses, local network addresses and your home folder's path are removed. Look it through before you share it.`, ["Cancel", "Write the Page"]);
  if (!ans) return;
  const sep = ON_WINDOWS() ? "\\" : "/";
  const out = p.real_path + sep + `${name} session.html`;
  const r = await busy("writing the page…", () => run(["share", p.real_path, "--format", "html", "--out", out]));
  if (r.ok) { post("/api/reveal", { path: p.real_path }); toast("Written: " + out); }
  else tell("The page could not be written", r.out + r.err);
}

// What changed / undo
function fileDiff(files, empty, act) {
  const box = h("div", { class: "stack" });
  if (!files.length) { box.append(h("p", { class: "dim", text: empty })); return box; }
  for (const f of files) {
    const lines = h("div", { class: "diff" });
    for (const l of String(f.diff || "").split("\n")) {
      lines.append(h("div", { class: l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : "", text: l }));
    }
    const det = h("details", {}, h("summary", {}, h("strong", { text: f.name || base(f.path) }), " ",
      h("span", { class: "dim small", text: `${f.state || ""} +${f.added || 0} −${f.removed || 0}${f.inside === false ? " · outside the project" : ""}` }),
      act ? " " : null, act ? act(f) : null), lines);
    box.append(det);
  }
  return box;
}
async function openChanges(p, session) {
  const d = await busy("reading the checkpoints…", () => J(...["changes", p.real_path, "--json"].concat(session ? ["--session", session] : [])));
  const s = sheet(`What changed: ${base(p.real_path)}`, "What did a session change?", 960);
  const sessions = d.sessions || [];
  if (sessions.length > 1) {
    const sel = h("select", { onchange: (e) => openChanges(p, e.target.value) },
      sessions.map((x) => h("option", { value: x, text: x === d.session ? (d.title || x) : x, selected: x === d.session })));
    s.head.append(h("span", { class: "grow" }), sel);
  }
  s.body.append(h("p", { class: "dim", text: d.title ? `Session “${d.title}”${d.worked_in ? ", " + d.worked_in : ""}.` : "The latest Claude Code session." }),
    fileDiff(d.files || [], "This session changed no file.", (f) => h("button", { class: "small", text: "Put Back…", onclick: async (e) => {
      e.preventDefault();
      if (!(await confirmIt(`Put “${f.name}” back as it was before the session?`, f.state === "added"
        ? "The session created this file; it is removed. A copy of it is kept in ~/.aht/changes-backups."
        : "What the file holds now is kept in ~/.aht/changes-backups first.", "Put Back"))) return;
      const r = await run(["changes", p.real_path, "--session", d.session, "--revert", f.path, "--apply"]);
      if (!r.ok) await tell("That did not work", r.out + r.err);
      openChanges(p, d.session);
    } })));
  s.foot.append(h("span", { class: "spacer" }), h("button", { text: "Close", class: "primary", onclick: closeSheet }));
}
async function openUndo(p, checkpoint) {
  const d = await busy("comparing with the copy…", () => J(...["undo", p.real_path, "--diff", "--json"].concat(checkpoint ? ["--checkpoint", checkpoint] : [])));
  const cps = d.checkpoints || [];
  const chosen = (d.checkpoint || {}).id;
  const s = sheet(`Undo a session: ${base(p.real_path)}`, "Undo a whole session", 960);
  if (cps.length) {
    s.head.append(h("span", { class: "grow" }), h("select", { onchange: (e) => openUndo(p, e.target.value) },
      cps.map((c) => h("option", { value: c.id, selected: c.id === chosen,
        text: `${when(c.at)} — ${AGENTS[c.agent] || c.agent}${c.title ? ": " + c.title : ""}` }))));
  }
  s.body.append(h("p", { class: "dim", text: cps.length
    ? "How the folder differs from its copy at the start of that session. Putting it back restores every file listed; what is there now is set aside in ~/.aht/undo first."
    : checkpointsOn() ? "aht has no copy of this folder yet. It makes one each time a Claude Code session starts here, and before another agent takes over."
    : "aht has no copy of this folder yet: “Copy the folder when a session starts” is off (Settings, Safety nets)." }),
    fileDiff(d.files || [], cps.length ? "Nothing changed since then." : ""));
  for (const w of (cps.length ? (d.blockers || []).concat(d.warnings || []) : [])) s.body.append(h("p", { class: "warn small", text: "⚠ " + w }));
  const files = (d.files || []).length;
  s.foot.append(h("span", { class: "spacer" }), h("button", { text: "Close", onclick: closeSheet }),
    h("button", { class: "primary", text: "Put Everything Back…", disabled: !files || (d.blockers || []).length || !chosen, onclick: async () => {
      if (!(await confirmIt(`Put “${base(p.real_path)}” back the way it was?`, `${plural(files, "file")} go back to how they were when the session started: changed files are restored, removed ones return, and files made since are taken out. All of it is set aside in ~/.aht/undo first, so nothing is lost.`, "Put Back"))) return;
      const r = await busy("putting the folder back…", () => J("undo", p.real_path, "--checkpoint", chosen, "--apply", "--json"));
      if (problems(r)) return tell("Not put back", problems(r));
      closeSheet();
      note(p, "Put back as it was when the session started. What the folder held is kept in " + (r.kept || "~/.aht/undo"));
    } }));
}

async function openRules(p, said) {
  const d = await J("rules", p.real_path, "--json");
  const s = sheet(`Project rules: ${base(p.real_path)}`, "One set of project rules", 760);
  s.body.append(md(d.summary || ""));
  const files = d.files || {};
  for (const [name, info] of Object.entries(files)) {
    s.body.append(h("div", { class: "row small" }, h("span", { class: "mono", text: name }),
      h("span", { class: "dim", text: typeof info === "object" ? `${info.bytes || 0} bytes${info.imports_agents ? " · brings in AGENTS.md" : ""}` : String(info) })));
  }
  if (said) s.body.append(h("p", { class: "okc", text: said }));
  const unify = async (prefer) => {
    const r = await J(...["rules", p.real_path, "--unify", "--apply", "--json"].concat(prefer ? ["--prefer", prefer] : []));
    openRules(p, r.applied ? `Done. AGENTS.md now holds the rules and ${d.claude_file || "CLAUDE.md"} brings them in. The earlier files are kept in ${r.backup || "~/.aht"}.`
      : r.needs_choice ? "The two files say different things now: choose which to keep." : "Nothing was changed.");
  };
  const cf = d.claude_file || "CLAUDE.md";
  s.foot.append(d.state === "claude-only" || d.state === "twins" ? h("button", { text: "Make One Set", onclick: () => unify() }) : null,
    // they differ: which one the one set holds is the person's choice
    d.state === "split" ? [h("span", { class: "dim", text: "Keep:" }), h("button", { text: `${cf}'s`, onclick: () => unify("claude") }),
      h("button", { text: "AGENTS.md's", onclick: () => unify("agents") }), h("button", { text: "Both", onclick: () => unify("both") })] : null,
    h("span", { class: "spacer" }), h("button", { text: "Close", class: "primary", onclick: closeSheet }));
}

async function openSecrets(p) {
  const s = sheet(p ? `Secrets in ${base(p.real_path)}'s history` : "Secrets in every history", "Secrets check", 860);
  const box = h("div", {}, h("p", { class: "dim" }, h("span", { class: "spin" }), "Looking…"));
  s.body.append(box);
  s.foot.append(h("span", { class: "spacer" }), h("button", { text: "Close", class: "primary", onclick: closeSheet }));
  const d = await J(...["secrets", "--json"].concat(p ? [p.real_path] : []));
  clear(box);
  const finds = d.finds || [];
  if (!finds.length) box.append(h("p", { class: "okc", text: "No key, token or password found." }));
  for (const f of finds) {
    box.append(h("div", { class: "row", style: "padding:6px 0;border-bottom:1px solid var(--line)" },
      h("div", { class: "grow" }, h("div", {}, h("strong", { text: f.kind }), " ", h("span", { class: "mono", text: f.masked })),
        h("div", { class: "dim small", text: `${base(f.project)} · ${AGENTS[f.agent] || f.agent} · ${f.where || ""}${f.times > 1 ? ` · ${f.times} times` : ""}${f.t ? " · " + when(f.t) : ""}` })),
      h("button", { text: "Remove…", onclick: () => removeSecret(f, p) })));
  }
}
async function removeSecret(f, p) {
  const d = await busy("looking for it…", () => J("secrets", "--redact", f.fingerprint, "--json"));
  if ((d.blockers || []).length) return tell("Not now", d.blockers.map((b) => "• " + b).join("\n\n"));
  if (!(await confirmIt(`Remove ${f.masked} from the histories?`, `It appears in ${plural(d.places || 0, "place")} in ${plural(d.files || 0, "history file")}; each is replaced by “[removed by aht]”. The files are copied to ~/.aht/redacted first. Backups and copies on other machines still hold it, so replace the key where it was issued as well.`, "Remove"))) return;
  const r = await busy("removing it…", () => run(["secrets", "--redact", f.fingerprint, "--apply"]));
  await tell(r.ok ? "Removed" : "That did not work", r.out + r.err);
  openSecrets(p);
}

// Second opinion (uses tokens) and the night shift (Linux)
async function tokensOK(key, what) {
  if (flag(key, false)) return true;
  const ok = await confirmIt(`Turn on ${what}?`, "This makes an agent read or work, which counts against your plan or API bill. aht's own work never uses tokens.", "Turn On");
  if (ok) await setConfig(key, true);
  return ok;
}
/** The level each agent of a second opinion works in, beside Start: from
 * `second-opinion <path> --task … --dry-run --json` ({perms: {agent: perm},
 * warnings, blockers}), which starts nothing; or what starting it answered.
 * `typed`: a task is typed (with none, the core's "say what both should do"
 * is no news). */
function opinionLevels(d, typed) {
  const by = d && d.perms && typeof d.perms === "object" ? d.perms : {};
  const stops = arr(d && d.blockers).filter((b) => typed || !/--task\b/.test(b));
  return [Object.keys(by).map((a) => permPart(d, a, { leaving: () => "the project's latest session" })),
    arr(d && d.warnings).map((w) => h("p", { class: "warn small", text: "⚠ " + w })),
    stops.length ? h("p", { class: "warn small", style: "white-space:pre-wrap", text: "Not possible now:\n\n" + stops.map((b) => "• " + b).join("\n\n") }) : null];
}
/** `started`: what starting it answered: the level each agent runs in
 * (`perms`, the core's words) and its warnings, shown beside Start until
 * another task is typed. */
async function openOpinion(p, runId, started) {
  if (!(await tokensOK("second_opinion", "second opinions"))) return;
  const all = ((await J("second-opinion", "--list", "--json")).opinions || []).filter((o) => o.project === p.real_path);
  const cur = runId || (all[0] || {}).id;
  const d = cur ? await busy("reading the answers…", () => J("second-opinion", "--show", cur, "--diff", "--json")) : {};
  const s = sheet(`Second opinion: ${base(p.real_path)}`, "A second opinion", 1000);
  if (all.length) {
    s.head.append(h("span", { class: "grow" }), h("select", { onchange: (e) => openOpinion(p, e.target.value) },
      all.map((o) => h("option", { value: o.id, selected: o.id === cur, text: `${when(o.started)} — ${String(o.task || "").slice(0, 40)}` }))));
  }
  const task = h("textarea", { rows: 2, style: "width:100%", placeholder: "A task for two agents, e.g. “make the parser accept empty lines”" });
  // beside Start: the level each agent works in, from a dry run of the task
  // typed (asked as the dialog opens, and again a moment after typing stops)
  const levels = h("div", { class: "stack opinion-levels", style: "margin-top:8px" });
  const start = h("button", { class: "primary", text: "Start", onclick: async () => {
    const t = task.value.trim();
    if (!t) return;
    const r = await busy("copying the project twice…", () => J("second-opinion", p.real_path, "--task=" + t, "--json"));
    if (problems(r)) return tell("Not started", problems(r));
    openOpinion(p, r.id, r);
  } });
  let asked = 0, wait = null;
  const look = async () => {
    const t = task.value.trim(), n = ++asked;
    // as it started, until another task is typed
    if (!t && started) return clear(levels).append(opinionLevels(started, false));
    const r = await J("second-opinion", p.real_path, "--task=" + t, "--dry-run", "--json");
    if (n !== asked || !levels.isConnected) return;          // typed again, or closed
    clear(levels).append(opinionLevels(r, !!t));
    // what stops this task stops Start too
    start.disabled = !!t && arr(r.blockers).length > 0;
  };
  task.addEventListener("input", () => { clearTimeout(wait); start.disabled = false; wait = setTimeout(look, 400); });
  s.body.append(h("p", { class: "dim", text: "Two agents work on the same task, each in a throwaway copy of the project; you compare and take one result. Both use tokens." }),
    h("p", { class: "dim small", text: "Claude Code may edit files in its throwaway copy at any level, since the project itself stays untouched; the commands it runs follow the level of the project's latest session, never higher. Kimi Code's run on its own never asks, so Kimi takes part only when that session runs in never-ask mode." }),
    h("div", { class: "row" }, task, start), levels);
  look();
  if (cur) {
    if (d.task) s.body.append(h("h3", { text: d.task }));
    if ((d.project_changed || []).length) s.body.append(h("p", { class: "warn small", text: "Changed in the project meanwhile: " + d.project_changed.join(", ") }));
    const res = d.results || {};
    const cols = h("div", { class: "row top", style: "align-items:stretch" });
    for (const a of d.agents || []) {
      const r = res[a] || {};
      const busyNow = ["working", "starting"].includes(r.state);
      const lv = (d.perms || {})[a];
      const level = lv && PERM_NAME[lv.level] ? h("span", { class: "badge" + (lv.level === "never" ? " waiting" : ""), text: permName(lv.level, lv.sandbox),
        title: arr(lv.flags).length ? "Flags: " + lv.flags.map(shellWord).join(" ") : "No flags" }) : null;
      cols.append(h("div", { class: "box grow", style: "min-width:280px" },
        h("div", { class: "row" }, h("strong", { text: AGENTS[a] || a }), h("span", { class: "badge", text: r.state || "?" }), level,
          r.seconds ? h("span", { class: "dim small", text: `${Math.round(r.seconds / 60)} min` }) : null,
          r.cost_usd ? h("span", { class: "dim small", text: `$${Number(r.cost_usd).toFixed(2)}` }) : null, h("span", { class: "grow" }),
          h("button", { class: "small", text: "Use These Changes…", disabled: busyNow || !!d.taken || !(r.files || []).length, onclick: async () => {
            const plan = await busy("checking…", () => J("second-opinion", "--take", cur, "--from", a, "--json"));
            if (problems(plan)) return tell("Not now", problems(plan));
            const n = (plan.files || []).length;
            if (!(await confirmIt(`Use ${AGENTS[a] || a}'s changes in “${base(p.real_path)}”?`, `${plural(n, "file")} of the project become ${AGENTS[a] || a}'s version. What they hold now is set aside in ~/.aht/undo first.`, "Use Them"))) return;
            const x = await busy("bringing them in…", () => J("second-opinion", "--take", cur, "--from", a, "--apply", "--json"));
            if (problems(x)) tell("Not done", problems(x));
            else note(p, `${AGENTS[a] || a}'s changes are in the project; what was there is kept in ${x.kept || ""}`);
            openOpinion(p, cur);
          } })),
        r.answer ? md(r.answer) : h("p", { class: "dim", text: busyNow ? "Working…" : "No answer." }),
        fileDiff(r.files || [], "No file changed.")));
    }
    s.body.append(cols);
  }
  s.foot.append(cur ? h("button", { text: "Remove the Copies…", onclick: async () => {
    if (!(await confirmIt("Remove the two copies?", "Their answers go with them. The project is not touched.", "Remove"))) return;
    await run(["second-opinion", "--discard", cur]); openOpinion(p);
  } }) : null, h("button", { text: "Look Again", onclick: () => openOpinion(p, cur) }),
  h("span", { class: "spacer" }), h("button", { class: "primary", text: "Close", onclick: closeSheet }));
}
async function openNightShift(p) {
  const remote = (S.status.handover || {}).default_remote;
  // the jobs, and a dry run for the level the session there starts in
  const [list, dry] = await Promise.all([J("night-shift", "--list", "--json"),
    J(...["night-shift", p.real_path, "--start", "now", "--back", "07:00", "--json"].concat(remote ? ["--to=" + remote] : []))]);
  const jobs = (list.jobs || []).filter((j) => j.project === p.real_path);
  const s = sheet(`Night shift: ${base(p.real_path)}`, "The night shift", 700);
  const task = h("textarea", { rows: 3, style: "width:100%", placeholder: "What the agent should do while you are away" });
  const startAt = h("input", { type: "time", value: "22:00" });
  const backAt = h("input", { type: "time", value: "07:00" });
  const now = h("input", { type: "checkbox" });
  const there = (dry.job || {}).remote || remote;
  const agent = dry.agent || "claude";
  s.body.append(task, h("div", { class: "row", style: "margin-top:6px" }, "Hand it over at", startAt,
    h("label", { class: "check" }, now, "now"), "and take it back from", backAt),
  permPart(dry, agent, { on: there, agent, leaving: (a) => `the ${a ? a + " " : ""}session here`,
    later: "aht reads the level again when the shift starts." }));
  for (const j of jobs.slice().reverse()) {
    s.body.append(h("div", { class: "row small", style: "padding:4px 0;border-bottom:1px solid var(--line)" },
      h("span", { class: "grow", text: `${when(j.start_at)} → ${when(j.back_at)}: ${j.task || ""}` }), h("span", { class: "badge", text: j.state || "" }),
      ["planned", "started"].includes(j.state) ? h("button", { class: "small", text: "Cancel", onclick: () => cancelNight(p, j) }) : null));
  }
  s.foot.append(h("span", { class: "spacer" }), h("button", { text: "Close", onclick: closeSheet }),
    h("button", { class: "primary", text: "Plan It", onclick: async () => {
      const t = task.value.trim();
      if (!t || !(await tokensOK("night_shift", "the night shift"))) return;
      const r = await busy("planning the night shift…", () => J(...["night-shift", p.real_path, "--task=" + t, "--back", backAt.value,
        "--start", now.checked ? "now" : startAt.value, "--apply", "--json"].concat(remote ? ["--to=" + remote] : [])));
      if (problems(r)) return tell("Not planned", problems(r));
      openNightShift(p);
    } }));
}
async function cancelNight(p, j) {
  // once it has started, the project is over there, and cancelling also
  // drops taking it back
  if (j.state === "started" && (await ask(`Cancel the night shift for “${base(p.real_path)}”?`,
    `The project stays on ${j.remote || "the other machine"} until you take it back (Take Back…). aht no longer brings it back by itself at ${when(j.back_at)}.`,
    ["Keep It", "Cancel the Shift"])) !== "Cancel the Shift") return;
  const r = await run(["night-shift", "--cancel", j.id]);
  const said = ((r.out || "") + (r.err || "")).trim();
  if (said) await tell("Night shift", said);
  openNightShift(p);
}

// ---- another agent on the other machine ------------------------------------------------
// Hand Over can start Codex, Kimi Code, Antigravity or Mistral Vibe on the other machine
// instead of resuming Claude Code's session there (`handover --agent X`), and
// Bring Here can open one of them here (`bring --agent X`).  That agent reads
// aht's summary of the work as its first turn, which uses tokens; Claude
// Code resuming its own session does not.  The dry run for the agent chosen
// carries the level it starts in (`perm`, phase 7b).
const OTHER_AGENTS = ["codex", "kimi", "agy", "vibe"];
/** The agents Hand Over can start on the other machine: Claude Code, and the
 * others the dry run says are installed there (`agents_there`: a list, or
 * {agent: its path or null}); a core that does not say: all of them (the
 * dry run for one that is missing there says so). */
function agentsThere(plan) {
  const t = plan && (plan.agents_there || (plan.there && typeof plan.there === "object" ? plan.there.agents : null));
  const has = Array.isArray(t) ? t : t && typeof t === "object" ? Object.keys(t).filter((a) => t[a]) : null;
  return ["claude", ...OTHER_AGENTS.filter((a) => !has || has.includes(a))];
}
/** …and Bring Here: the agent CLIs installed on this machine. */
const agentsHere = () => ["claude", ...OTHER_AGENTS.filter((a) => (S.status.agent_clis || {})[a])];
/** What starting `agent` costs.  `on`: the other machine (Hand Over), or
 * null (here: Bring Here); `task`: a task given with it; `d`: the dry run
 * for that agent: its `tokens` (the core's sentence), as given; Kimi below
 * never-ask opens without reading the summary (`first_prompt`). */
function agentCost(agent, on, task, d) {
  const label = AGENTS[agent] || agent, where = on ? `on ${on}` : "here";
  if (agent !== "claude" && d && typeof d.tokens === "string" && d.tokens.trim()) return sentence(d.tokens).trim();
  if (agent === "claude") {
    if (task) return `With a task, Claude Code starts on it at once ${where}: that uses tokens.`;
    return on ? `Claude Code resumes its own session on ${on}: nothing runs until someone types there, so it uses no tokens.`
      : "Claude Code's own session opens here: nothing runs until you type, so it uses no tokens.";
  }
  if (agent === "kimi" && d && (d.kimi_reads === false || (typeof d.first_prompt === "string" && d.first_prompt.trim()))) {
    return `Kimi Code opens ${where} without reading the summary: its run that reads it first works only in never-ask mode, so you paste the first message aht shows you${on ? " into its window there" : ""}. That turn uses tokens.`;
  }
  return `Starting ${label} ${where} uses tokens: it reads aht's summary of the work as its first turn.`;
}
/** Kimi below never-ask, started by Hand Over or Bring Here: the first
 * message to paste (`first_prompt`), or null. */
const farFirst = (d) => (d && typeof d.first_prompt === "string" && d.first_prompt.trim() ? d.first_prompt.trim() : null);
/** What happens there, in one sentence. */
function agentStarts(agent, on) {
  const where = on ? `on ${on}` : "here";
  return agent === "claude" ? (on ? "The session is resumed there" : "Its session opens here in a new terminal")
    : `${AGENTS[agent] || agent} starts ${where} with aht's summary of the work`;
}
/** The "Agent there" (Hand Over) or "Agent here" (Bring Here) choice. */
function agentPicker(label, agents, chosen, onPick, disabled) {
  return h("div", { class: "row agent-pick" }, h("strong", { text: label }),
    h("select", { class: "agent-choice", disabled, onchange: (e) => onPick(e.target.value) },
      agents.map((a) => h("option", { value: a, selected: a === chosen,
        text: a === "claude" ? "Claude Code (its own session)" : AGENTS[a] || a }))));
}

/** A row of the Sessions board for a window aht started for an agent other
 * than Claude Code on another machine: its status comes from the window's
 * output, not from the agent's records.  `raw_status` "working" (output in
 * the last 15 s), "quiet" (none for `quiet_for` seconds: done, or it waits
 * for you), "exited" (the agent ended; the window closes a minute later);
 * `not_running`: the agent there ended (its window may be gone).  null for
 * any other row (Claude Code keeps its own words). */
function windowStatus(s) {
  if (!s || !(s.not_running === true || ["working", "quiet", "exited"].includes(s.raw_status))) return null;
  if (s.raw_status === "exited") return { text: "exited", cls: "", hint: null };
  if (s.not_running === true) return { text: "not running", cls: "", hint: null };
  if (s.raw_status === "working") return { text: "working", cls: "working", hint: null };
  return { text: quietFor(s.quiet_for), cls: "quiet", hint: "done, or it waits for you" };
}
/** "quiet for 6 min", from seconds, as the core says it (window_words). */
function quietFor(sec) {
  const n = Number(sec);
  if (sec == null || !isFinite(n) || n < 0) return "quiet";
  const m = Math.floor(n / 60);
  return m < 1 ? "quiet for under a minute" : m < 120 ? `quiet for ${m} min` : `quiet for ${Math.floor(m / 60)} h`;
}
/** Seconds in words: "40 s", "2 min". */
const span = (sec) => (sec < 60 ? `${Math.round(sec)} s` : `${Math.floor(sec / 60)} min`);

/** Take Back with --stop ends the agent there only when that is safe.  For
 * an agent other than Claude Code: when its window has shown no output for
 * 2 minutes and its last turn has ended.  Otherwise it refuses, with
 * `not-quiet` (the agent there still prints) or `turn-open` (a turn is not
 * finished, or aht cannot see whether it is: `seen` false); at --apply also
 * `no-reaction` (it did not quit on its quit keys).  Read from `stop`
 * ({stopped, reason, quiet_for, quit_keys, seen}), a bare reason
 * (`stop_reason`), or the core's own sentence in the blockers or warnings
 * ("Codex on box has been quiet for only 1 min — wait, or end it yourself
 * (--stop needs 2 minutes without output)", "Codex's last turn is still open
 * on box — wait, or end it yourself").  null: no such refusal.  `said`: the
 * core's sentence, `others`: the other blockers (not the agent's own
 * processes there, which end with it). */
const STOP_REASONS = ["not-quiet", "turn-open", "no-reaction"];
const NOT_QUIET = /quiet for only|still prints/i, TURN_OPEN = /turn is still open|turn is not finished|whether its turn ended/i,
  NO_REACTION = /did not react to its quit keys/i;
const STOP_TEXT = { "not-quiet": NOT_QUIET, "turn-open": TURN_OPEN, "no-reaction": NO_REACTION };
const refusalText = (t) => NOT_QUIET.test(t) || TURN_OPEN.test(t) || NO_REACTION.test(t);
function stopRefusal(d, p) {
  if (!d || typeof d !== "object") return null;
  const objs = [d.stop_refused, d.stop, d.stopped].filter((x) => x && typeof x === "object");
  const o = objs.find((x) => STOP_REASONS.includes(x.reason)) || {};
  let reason = o.reason || [d.stop_refused, d.stop_reason, d.reason].find((x) => STOP_REASONS.includes(x)) || null;
  const blockers = arr(d.blockers).map(String), texts = blockers.concat(arr(d.warnings).map(String));
  let said = typeof o.text === "string" ? o.text : reason ? texts.find((t) => STOP_TEXT[reason].test(t)) || null : null;
  if (!reason) {
    said = texts.find(refusalText) || null;
    if (!said) return null;
    reason = STOP_REASONS.find((r) => STOP_TEXT[r].test(said));
  }
  const agent = o.agent || d.agent_there || awayAgent(p) || OTHER_AGENTS.find((a) => said && said.includes(AGENTS[a])) || null;
  const m = said && /quiet for only (\d+)\s*(s|sec|min)/i.exec(said), n = said && /needs (\d+) minutes?/i.exec(said);
  const quiet = o.quiet_for != null ? Number(o.quiet_for) : d.quiet_for != null ? Number(d.quiet_for)
    : m ? Number(m[1]) * (/^m/i.test(m[2]) ? 60 : 1) : null;
  // the agent's own processes there ("codex (4242)"): they end with it, no news
  const own = (b) => !!agent && /^still running in this folder/i.test(b)
    && b.slice(b.indexOf(":") + 1).split(",").every((x) => x.trim().toLowerCase().startsWith(agent));
  return { reason, agent, label: AGENTS[agent] || agent || "The agent", machine: o.machine || d.remote || (p && (p.away_remote || p.away)) || null,
    quiet, need: Number(o.need || o.quiet_needed || d.quiet_needed) || (n ? Number(n[1]) * 60 : 120), said,
    seen: o.seen !== false && !(said && /whether its turn ended/i.test(said)), keys: arr(o.quit_keys).map(String),
    others: blockers.filter((b) => b !== said && !refusalText(b) && !own(b)) };
}
/** The refusal in plain words, and what to do. */
function stopWords(x) {
  const who = x.label + (x.machine ? ` on ${x.machine}` : "");
  if (x.reason === "not-quiet") {
    return { title: `${who} is still printing`,
      text: `${x.label}'s window ${x.machine ? "there " : ""}showed new output ${x.quiet != null ? span(x.quiet) + " ago" : "a moment ago"}, so it may be in the middle of its work. aht ends it only after ${span(x.need)} without new output.`
        + `\n\nWhat to do: wait until it has been quiet for ${span(x.need)}, then choose Take Back again. Or open its window, see what it does, and end it yourself.` };
  }
  if (x.reason === "no-reaction") {
    return { title: `${who} did not quit`,
      text: `aht pressed its quit keys${x.keys.length ? ` (${x.keys.join(" ")})` : ""}, and ${x.label} still runs.`
        + "\n\nWhat to do: open its window and end it yourself, then choose Take Back again." };
  }
  if (!x.seen) {
    return { title: `aht cannot tell whether ${x.label}'s last turn ended`,
      text: `aht cannot see ${x.label}'s own last message${x.machine ? ` on ${x.machine}` : ""}, so it cannot tell whether its turn ended, and it does not end an agent in the middle of a turn.`
        + "\n\nWhat to do: open its window and look. If it is done, end it yourself there, then choose Take Back again." };
  }
  return { title: `${x.label}'s last turn is not finished`,
    text: `${who} has not finished its last turn: it may still be working on it, or wait for an answer. aht does not end an agent in the middle of a turn.`
      + "\n\nWhat to do: open its window to see what it waits for; answer it, or let it finish. Then choose Take Back again. Or end it yourself there." };
}
/** The refusal as a question: Open Its Window (`attach --window`), Try Again. */
async function stopRefused(p, x, after) {
  const w = stopWords(x);
  const extra = x.others.length ? h("p", { class: "warn small stop-others", style: "white-space:pre-wrap", text: "Also in the way:\n\n" + x.others.map((b) => "• " + b).join("\n") }) : null;
  const pick = await ask(w.title, (after ? "Nothing was taken back. " : "") + w.text, ["Cancel", "Open Its Window", "Try Again"], extra);
  if (pick === "Try Again") return takeBack(p);
  if (pick === "Open Its Window") return openWindowThere(p);
}
/** Take Back from another agent: what it did there is summed up for Claude
 * Code's session here (`catchup`: {agent, relay, brief}), which aht's hook
 * tells it as it opens. */
function caughtUp(d, remote) {
  const c = d && d.catchup && typeof d.catchup === "object" ? d.catchup : null;
  if (!c) return "";
  return `\nWhat ${AGENTS[c.agent] || c.agent || "the agent"} did on ${remote} is summed up for your Claude Code session${c.brief ? ": " + c.brief : "."}`;
}
/** The agent working on a project on another machine (`away_agent`, from
 * the away record's `agent`), or null when the core does not say. */
function awayAgent(p) {
  if (!p) return null;
  const a = p.away_agent || (p.away && typeof p.away === "object" ? p.away.agent : null);
  return typeof a === "string" && a ? a : null;
}
const awayAgentLabel = (p) => (awayAgent(p) ? AGENTS[awayAgent(p)] || awayAgent(p) : null);

/** Hand Over's dry run blocks over a copy there that was worked on since
 * both copies last agreed, at a sync, a handover or a take back
 * (`copy_changed`: {changed, new, removed, history, files, since}, as a
 * pause counts them; or only its blocker, which names --replace-there,
 * the way past), or null. */
const PAST = /--replace-there/;
function changedThere(plan) {
  const c = plan && plan.copy_changed;
  if (c && typeof c === "object") return c;
  const b = ((plan && plan.blockers) || []).find((x) => PAST.test(x));
  return b ? { said: b } : null;
}
/** The block, and the ways past it: bring that work here first (Take Back
 * on the copy), or replace it (`--replace-there`: it is set aside there),
 * which the Hand Over question then names once more. */
async function changedCopyBlock(p, plan, ch, remote) {
  const name = base(p.real_path), c = counted(ch);
  // other blockers come first: no way past this one helps with those
  const others = (plan.blockers || []).filter((b) => !PAST.test(b));
  if (others.length || plan.error) return note(p, "Cannot be handed over now:\n\n" + problems({ blockers: others, error: plan.error }));
  const pick = await ask(`The copy on ${remote} was changed there`,
    `The copy of “${name}” on ${remote} was worked on since ${ch.since ? clock(ch.since) : "the two copies last agreed"}${c ? ` (${c})` : ""}`
    + (filesIn(ch).length ? ":" + listed(ch) : ch.said ? `:\n${sentence(ch.said).trim()}` : ".")
    + `\n\nHanding it over would replace that work. Bring it here first, or replace it: what is replaced is set aside on ${remote} first (in ~/.aht/remote/replaced/), not deleted.`,
    ["Cancel", "Replace Them There…", "Bring Them Here…"]);
  if (pick === "Bring Them Here…") return takeBack(p, true);
  if (pick === "Replace Them There…") return handOver(p, ch);
}

/** Hand Over to a Windows PC (the dry run's `pc`, its system there, or the
 * machine's own): aht copies the project there and starts nothing; the
 * PC's tray offers Continue here.  Only Claude Code continues there. */
const toPc = (plan, remote) => plan.pc === true || (farSystem(plan) || (remoteRow(remote) || {}).system) === "Windows";
const pcNoStart = (pc) => `No session starts on ${pc}: aht copies the project there, and the PC's tray offers “Continue here”, which opens it in Claude Code. This folder is marked as away until you take it back.`;
/** The core started no session there (`started: false` with `start_reason`
 * or `reason` "windows", on its own or under `start`). */
const startedNot = (d) => [d, d && d.start].some((x) => x && typeof x === "object" && x.started === false
  && (x.start_reason || x.reason) === "windows");

// Handover (Linux)
/** `replacing`: the changed copy there that Replace Them There… lets the
 * handover replace (`--replace-there`). */
async function handOver(p, replacing) {
  const remote = (S.status.handover || {}).default_remote, name = base(p.real_path);
  const past = replacing ? ["--replace-there"] : [];
  note(p, null);
  const plan = await busy(`checking ${name}…`, () => J("handover", p.real_path, "--json", "--to", remote, ...past));
  const ch = changedThere(plan);
  if (ch && !replacing) return changedCopyBlock(p, plan, ch, remote);
  // names that cannot exist there, or a folder there that is another
  // project's: said in parts, with the way past
  if (problems(plan) && (arr(plan.names).length || arr(plan.blockers).some((x) => WHERE.test(x) || /`/.test(x)))) {
    const why = blockedPart(plan, remote, null, "Cannot be handed over now"), sys = farSystem(plan);
    return note(p, why ? "" : "Cannot be handed over now:", null, [why,
      namesPart(plan, `${remote}${sys ? ` (${SYSTEMS[sys] || sys})` : ""}`, () => handOver(p, replacing))]);
  }
  if (problems(plan)) return note(p, "Cannot be handed over now:\n\n" + problems(plan));
  const n = plan.plan || {};
  // the folder there, when it is not at the same path (path mapping)
  const far = plan.there_path || plan.remote_path;
  let body = `${n.files || 0} file(s) to send (${bytes(n.bytes)}), history ${bytes(n.history_bytes)}.\nSession: ${plan.title || "the one used last"}`;
  if (far && !sameDir(far, p.real_path)) body += `\nOn ${remote} it goes to ${far}.`;
  if (n.install_claude) body += `\nClaude Code ${n.install_claude} gets installed on ${remote}.`;
  const stay = plan.outside_not_carried || [];
  if (stay.length) body += "\n\nFiles outside the project that stay here:\n" + stay.slice(0, 6).map((x) => "• " + x).join("\n");
  if (replacing) {
    const r = ch || replacing, c = counted(r);
    body += `\n\nThe work done in the copy on ${remote}${r.since ? " since " + clock(r.since) : ""}${c ? ` (${c})` : ""} is set aside there first (in ~/.aht/remote/replaced/), not deleted:` + listed(r);
  }
  // …which the core says too, as a warning: once is enough
  for (const w of plan.warnings || []) if (!(replacing && /aside there$/.test(w))) body += "\n\n⚠ " + w;
  for (const t of arr(plan.notes)) body += "\n\n" + sentence(t).trim();
  // Agent there: Claude Code resumes its own session (the plan above), or
  // another agent starts with the summary: its own dry run (`--agent X`),
  // asked when it is chosen, says what stops it and the level it starts in.
  // A PC starts no session (its tray offers Continue here): no choice
  const pc = toPc(plan, remote);
  const source = plan.agent || "claude", agents = pc ? ["claude"] : agentsThere(plan), dries = { claude: plan };
  let chosen = "claude";
  const there = h("div", { class: "stack agent-there" });
  const paint = () => {
    const d = dries[chosen], label = AGENTS[chosen] || chosen;
    const stop = d && chosen !== "claude" ? problems(d) : null;
    clear(there).append(agents.length > 1 ? agentPicker("Agent there", agents, chosen, pick) : null,
      !d ? h("div", { class: "dim small" }, h("span", { class: "spin" }), `asking ${remote} about ${label}…`)
        : stop ? h("p", { class: "warn small", style: "white-space:pre-wrap", text: `Not possible with ${label}:\n\n${stop}` })
        : pc ? [h("div", { class: "small starts", text: pcNoStart(remote) }), permPart(d, chosen, { on: remote, agent: source, leaving: (a) => `the ${a ? a + " " : ""}session here` })]
        : [h("div", { class: "small starts", text: `${agentStarts(chosen, remote)} and this folder is marked as away until you take it back.` }),
          h("div", { class: "dim small tokens", text: agentCost(chosen, remote, false, d) }),
          chosen === "claude" ? null : arr(d.warnings).filter((w) => !arr(plan.warnings).includes(w)).map((w) => h("p", { class: "warn small", text: "⚠ " + w })),
          permPart(d, chosen, { on: remote, agent: source, leaving: (a) => `the ${a ? a + " " : ""}session here` })]);
    // Hand Over waits for the answer about the agent chosen, and what stops it stops Hand Over
    const go = there.closest(".box") && there.closest(".box").querySelector("button.primary");
    if (go) go.disabled = !d || !!stop;
  };
  const pick = async (a) => {
    chosen = a;
    if (!dries[a]) {
      paint();
      const d = await dryRun(["handover", p.real_path, "--json", "--to", remote, "--agent", a, ...past]);
      dries[a] = d;
      if (chosen !== a || !there.isConnected) return;
    }
    paint();
  };
  paint();
  if (!(await confirmIt(`Hand “${name}” over to ${remote}?`, body, replacing ? "Replace and Hand Over" : "Hand Over", [there, gitattrPart(plan)]))) return;
  const agent = chosen === "claude" ? [] : ["--agent", chosen], label = AGENTS[chosen] || chosen;
  S.moving = p.real_path;             // its own record of it is no unfinished handover
  const d = await busy(`handing ${name} over…`, () =>
    job(["handover", p.real_path, "--apply", "--json", "--to", remote, ...past, ...agent], "handing over", true).then((a) => a.json || {}))
    .finally(() => { S.moving = null; });
  const s = d.sent || {};
  // Kimi below never-ask opened without reading the summary: the first
  // message to paste into its window there
  const first = !problems(d) && chosen === "kimi" ? farFirst(d) : null;
  note(p, problems(d) ? "The handover did not go through:\n\n" + problems(d)
    : `Handed over to ${remote}: ${s.files || 0} file(s) sent, ${bytes(s.wire_bytes)} over the network.`
      + (pc || startedNot(d) ? " No session started there: its tray offers “Continue here”." : agent.length ? ` ${label} started there with aht's summary of the work.` : ""), null,
    first ? [firstPromptPart(first), h("button", { class: "small", text: "Open Its Window", onclick: () => openWindowThere(p) })] : undefined);
  refresh();
}
/** Peek: the last lines the agent's window on the other machine shows
 * (`attach --peek --json`: {agent, open, status, raw_status, quiet_for,
 * screen, error}), in a sheet; nothing is typed there. */
async function peekThere(p) {
  const remote = p.away_remote || p.away, label = awayAgentLabel(p) || "The agent";
  const d = await busy(`looking at ${label} on ${remote}…`, () => dryRun(["attach", p.real_path, "--peek", "--json"]));
  const s = sheet(`${label} on ${remote}`, "Hand a project over", 820);
  const ws = windowStatus(d), lines = arr(d.screen).map(String);
  s.body.append(h("div", { class: "row peek-state" }, ws || d.status ? h("span", { class: "badge " + (ws ? ws.cls : ""), text: ws ? ws.text : d.status }) : null,
    ws && ws.hint ? h("span", { class: "dim small", text: ws.hint }) : null),
  d.error ? h("p", { class: "warn small", style: "white-space:pre-wrap", text: d.error }) : null,
  lines.length ? h("pre", { class: "peek", text: lines.join("\n") }) : !d.error ? h("p", { class: "dim", text: "Its window shows nothing yet." }) : null,
  h("p", { class: "dim small", text: "The last lines its window shows; nothing is typed there. Open Its Window to answer it or end it." }));
  s.foot.append(h("button", { text: "Look Again", onclick: () => { closeSheet(); peekThere(p); } }),
    h("button", { text: "Open Its Window", onclick: () => openWindowThere(p) }),
    h("span", { class: "spacer" }), h("button", { text: "Close", class: "primary", onclick: closeSheet }));
}
/** The window aht runs the agent in on the other machine, in a new terminal. */
async function openWindowThere(p) {
  const r = await run(["attach", p.real_path, "--window"]);
  if (r.ok) return toast("Its window opens in a new terminal.");
  tell("Its window did not open", ((r.err || "") + (r.out || "")).trim() || "aht gave no answer.");
}
/** Take Back, and Bring Them Here (`copy`): the same plan, the same "changed
 * on both: keep both", the same set-aside.  For a copy kept in sync whose
 * sync paused over work done there, `reclaim` brings that work here
 * (`mode: "copy"`), and then the sync runs; nothing was handed over, so no
 * session there is ended for it.  When that would remove more files here
 * than aht removes without asking (`removals.over`), the question names
 * them and going ahead allows them (`--allow-removals`). */
async function takeBack(p, copy) {
  // aht ends no session on a PC: one open there blocks, in the core's words
  const name = base(p.real_path), stop = (awayOf(p) || {}).pc ? [] : copy ? [] : ["--stop"];
  note(p, null);
  let plan = await busy(`checking ${name}…`, () => J("reclaim", p.real_path, ...stop, "--json"));
  copy = plan.mode ? plan.mode === "copy" : !!copy;
  // Bring Them Here that would remove many files here asks before it does
  if (copy) plan = pastRemovals(plan);
  // the agent there cannot be ended safely yet (--stop): why, and what to do
  const refused = copy ? null : stopRefusal(plan, p);
  if (refused) return stopRefused(p, refused);
  if (problems(plan)) return note(p, (copy ? "The changes cannot be brought here now:\n\n" : "Cannot be taken back now:\n\n") + problems(plan));
  const remote = plan.remote || p.away_remote || p.away || p.mirror;
  const n = (plan.plan || {}).project || {};
  let body = `${n.take || 0} file(s) changed there, ${n.new || 0} new, ${n.delete || 0} removed. Whatever they replace here is set aside, not deleted.`;
  const hs = (plan.plan || {}).history || {};
  if (copy && (hs.take || hs.new)) body += "\nThe conversation that went on there comes too.";
  // removals over the limit (`removals.over`): named here, and going ahead allows them
  const gone = copy ? removalsOf(plan) : null, allow = gone && gone.over ? ["--allow-removals"] : [];
  if (allow.length) {
    body += `\n\nIt removes ${removalsCounted(gone)} here, because they are gone from the copy on ${remote}: more than aht removes without asking, so going ahead allows it, once. They are set aside here first, not deleted:`
      + listed({ files: gone.files, removed: gone.removed }) + `\nIf they went missing on ${remote} by mistake, cancel.`;
  }
  // the sync runs after it only when Keep in sync with that machine is on
  if (copy && p.mirror === remote) body += `\n\nThen the sync runs, and the copy on ${remote} is the same as this one again.`;
  const far = awayAgent(p) && awayAgent(p) !== "claude" ? awayAgentLabel(p) : null, q = (plan.stop || plan.window || {}).quiet_for;
  if (plan.would_stop) body += far ? `\n\n${far} on ${remote} is ended first: it has been ${q != null ? quietFor(q) : "quiet"}, and its last turn has ended.`
    : `\n\nThe idle session on ${remote} is ended first.`;
  const both = Object.values(plan.conflicts || {}).flat();
  const title = copy ? `Bring the changes on ${remote} here?` : `Take “${name}” back from ${remote}?`;
  // across systems: line endings, names this machine cannot hold, .gitattributes
  const across = crossNotes(plan, "here");
  let extra = [];
  if (both.length) {
    body += "\n\nChanged on BOTH machines:\n" + both.slice(0, 6).map((x) => "• " + x).join("\n") +
      `\n\nKeep Both leaves your version in place and puts the one from ${remote} next to it.`;
    const pick = await ask(title, body, ["Cancel", `Use the Versions from ${remote}`, "Keep Both"], across);
    if (!pick) return;
    if (pick.startsWith("Use")) extra = ["--prefer", "there"];
  } else if (!(await confirmIt(title, body, copy ? "Bring Them Here" : "Take Back", across))) return;
  const d = await busy(copy ? `bringing the changes on ${remote} here…` : `taking ${name} back…`, () =>
    job(["reclaim", p.real_path, ...stop, "--apply", "--json", ...extra, ...allow], copy ? "bringing them here" : "taking back", true).then((a) => a.json || {}));
  // the agent there began to print again, or opened a turn, after the dry run
  const late = !copy && !d.applied ? stopRefusal(d, p) : null;
  if (late) { refresh(); return stopRefused(p, late, true); }
  const kept = d.set_aside ? "\nReplaced files are kept in: " + d.set_aside : "";
  note(p, problems(d) ? (copy ? "The changes did not come here:\n\n" : "Taking it back did not go through:\n\n") + problems(d)
    : copy ? `The changes from ${remote} are here.${syncedAfter(d, remote)}${kept}`
    : "Back on this computer, files and history." + kept + caughtUp(d, remote), !problems(d) && !copy ? (d.catchup || {}).brief || null : null);
  refresh();
}
async function keepInSync(p, on) {
  const remote = (S.status.handover || {}).default_remote;
  note(p, null);
  // a folder that is itself a copy kept in sync from that machine is refused
  const r = await busy(on ? `keeping ${base(p.real_path)} in sync…` : "turning Keep in sync off…", () => run(["mirror", p.real_path].concat(on ? ["--on", "--to", remote] : ["--off"])));
  if (!r.ok) note(p, (on ? "Keep in sync was not turned on:\n\n" : "Keep in sync was not turned off:\n\n") + ((r.err + r.out).trim() || "aht gave no answer."));
  else if (on) note(p, `Kept in sync with ${remote}; the first copy runs in the background.`);
  refresh();
}

// ---- Keep in sync: look before a sync overwrites -------------------------------------
// Before each sync, aht compares the copy on the other machine with its own
// list from the last sync.  When that copy was worked on, when the sync
// would remove many files there, or when the folder there holds something
// else, the sync pauses, sends nothing, and the project asks
// (`mirror_paused`: {at, reason, changed, new, removed, files}).

/** What each pause asks, by its `reason`; "released" (a Release) has the
 * older banner with Turn Sync Back On…. */
const SYNC_ASKS = ["changed", "removals", "other-folder"];
const asksForSync = (p) => { const x = syncPaused(p); return !!x && SYNC_ASKS.includes(x.reason); };
/** "2 changed, 1 new and 1 removed", from a pause's counts. */
function counted(x) {
  const parts = [x.changed ? `${x.changed} changed` : null, x.new ? `${x.new} new` : null, x.removed ? `${x.removed} removed` : null,
    x.history ? `${plural(x.history, "conversation")} continued` : null].filter(Boolean);
  return parts.length > 1 ? parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1] : parts[0] || "";
}
/** The files a pause names (the core sends the first 50), and how many it
 * stands for: the changed, new and removed ones; for another folder there,
 * every file in it (`total`). */
const filesIn = (x) => (Array.isArray(x.files) ? x.files : []);
const filesOf = (x) => Math.max(filesIn(x).length, x.reason === "other-folder" ? x.total || 0 : (x.changed || 0) + (x.new || 0) + (x.removed || 0));
/** …as lines for a question: the first 8. */
function listed(x) {
  const f = filesIn(x), total = filesOf(x);
  return f.length ? "\n" + f.slice(0, 8).map((y) => "• " + y).join("\n") + (total > 8 ? `\n… and ${total - Math.min(f.length, 8)} more` : "") : "";
}
/** What a sync with Replace Them, or Bring Them Here, would remove (the dry
 * run's `removals`: {removed, total, files (the first 50), over}); null when
 * nothing goes, or from an older core that does not say.  `over`: more than
 * aht removes without asking, so going ahead allows them (`--allow-removals`). */
function removalsOf(plan) {
  const r = plan && plan.removals;
  return r && typeof r === "object" && r.removed > 0 ? r : null;
}
/** "25 of the 34 files", or "3 files". */
const removalsCounted = (r) => (r.total > r.removed ? `${r.removed} of the ${r.total} files` : plural(r.removed, "file"));
/** A dry run whose removals are over the limit, without the blockers (and
 * warnings) that allowing them lifts: those name --allow-removals, which
 * the question then asks for.  Any other blocker stays: a folder there that
 * is missing or empty cannot be allowed. */
const ALLOWS = /--allow-removals/;
function pastRemovals(plan) {
  if (!(plan && plan.removals && plan.removals.over)) return plan;
  const keep = (xs) => (xs || []).filter((x) => !ALLOWS.test(x));
  return Object.assign({}, plan, { blockers: keep(plan.blockers), warnings: keep(plan.warnings) });
}
/** What a sync that ran after Bring Them Here (or Replace Them, or Allow
 * the Removals) says: " The copy on box is the same as this one again." */
function syncedAfter(d, to) {
  const rows = d.mirrored || (d.sync ? [d.sync] : []);
  const r = rows.find((x) => x && x.status) || null;
  if (!r) return "";
  if (r.status === "synced") return ` The copy on ${to} is the same as this one again.`;
  if (r.status === "paused") return ` The sync with ${to} is still paused: ${r.reason || "see the project"}.`;
  return ` The sync with ${to} did not run: ${r.reason || r.status}.`;
}

/** The pause on the project row, with what it asks. */
function pausedBanner(p) {
  const x = syncPaused(p), to = p.mirror;
  if (SYNC_ASKS.includes(x.reason)) return syncAsks(p, x, to);
  return h("div", { class: "callout row" },
    h("div", { class: "grow" }, h("strong", { text: `Keep in sync with ${to} is paused` }),
      h("div", { class: "small", text: x.reason === "released"
        ? `You released this project${x.at ? " at " + clock(x.at) : ""}, so the copy on ${to} stays as it is. Turning the sync back on makes that copy the same as this one again.`
        : `The copy on ${to} stays as it is until you turn the sync back on.` })),
    h("button", { class: "small", text: "Turn Sync Back On…", onclick: () => resumeSync(p) }),
    helpBtn("Hand a project over"));
}
async function resumeSync(p) {
  const x = syncPaused(p) || {}, to = p.mirror, name = base(p.real_path);
  if (!(await confirmIt(`Keep “${name}” in sync with ${to} again?`, `The next sync makes the copy on ${to} the same as this one. `
    + `If that copy was worked on${x.reason === "released" ? " since you released it" : " there"}, the sync pauses first and sends nothing, `
    + "and asks you here what happens to that work: bring it here, replace it (it is set aside there first, not deleted), or stop syncing.", "Turn It On"))) return;
  const r = await busy(`turning the sync with ${to} back on…`, () => run(["mirror", p.real_path, "--on", "--to", to]));
  note(p, r.ok ? `Kept in sync with ${to} again; the next copy runs in the background.`
    : "The sync was not turned back on:\n\n" + ((r.out + r.err).trim() || "aht gave no answer."));
  refresh();
}
/** A sync that paused to ask: what it found, and the ways on.
 * - changed: [Bring Them Here…] (Take Back on the copy), [Replace Them…]
 *   (`mirror --replace`: theirs are set aside there), [Stop Syncing];
 * - removals: [Allow the Removals…] (`mirror --allow-removals`), [Stop Syncing];
 * - other-folder: [Replace Them…], [Stop Syncing]. */
function syncAsks(p, x, to) {
  const at = x.at ? ` at ${clock(x.at)}` : "", c = counted(x);
  const [title, text] = {
    changed: [`Keep in sync with ${to} paused: the copy there was changed`,
      `The copy on ${to} was worked on since the last sync${c ? ` (${c})` : ""}. The sync paused${at} and sent nothing, so that work is still there.`],
    removals: [`Keep in sync with ${to} paused: it would remove ${x.removed ? plural(x.removed, "file") : "many files"} there`,
      `${x.removed ? plural(x.removed, "file") : "Many files"} ${x.removed === 1 ? "is" : "are"} gone here since the last sync: more than aht removes from the copy on ${to} without asking. The sync paused${at} and sent nothing.`],
    "other-folder": [`Keep in sync with ${to} paused: the folder there holds something else`,
      `The folder on ${to} already holds ${x.total ? plural(x.total, "file") : "files"} that ${x.total === 1 ? "is" : "are"} not this project's${x.marker ? " (another project's)" : ""}. The first sync paused${at} and sent nothing.`],
  }[x.reason];
  const f = filesIn(x);
  const more = filesOf(x) - Math.min(f.length, 5);
  return h("div", { class: "callout sync" },
    h("strong", { text: title }),
    h("div", { class: "small", text }),
    f.length ? h("ul", { class: "files small mono" }, f.slice(0, 5).map((y) => h("li", { text: y })),
      more > 0 ? h("li", { class: "dim", text: `… and ${more} more` }) : null) : null,
    h("div", { class: "row" },
      x.reason === "changed" ? h("button", { class: "small primary", text: "Bring Them Here…", onclick: () => takeBack(p, true) }) : null,
      x.reason !== "removals" ? h("button", { class: "small", text: "Replace Them…", onclick: () => syncAnyway(p, "replace") }) : null,
      x.reason === "removals" ? h("button", { class: "small", text: "Allow the Removals…", onclick: () => syncAnyway(p, "removals") }) : null,
      h("button", { class: "small", text: "Stop Syncing", onclick: () => stopSyncing(p) }),
      h("span", { class: "grow" }), helpBtn("Hand a project over")));
}
/** Replace Them (`mirror --replace`) or Allow the Removals (`mirror
 * --allow-removals`): the dry run looks at the copy there again (`check`:
 * {changes, removals, pause}; `would`; `aside`: where it is set aside
 * there); the question names what this one sync replaces or removes there
 * (`removals`), and where it is set aside first; then the sync runs once
 * with it, and with --allow-removals when those are over the limit. */
async function syncAnyway(p, how) {
  const to = p.mirror, name = base(p.real_path), flag = how === "replace" ? "--replace" : "--allow-removals";
  note(p, null);
  // removals over the limit ask here, before Replace Them allows them
  const plan = pastRemovals(await busy(`checking the copy on ${to}…`, () => dryRun(["mirror", p.real_path, flag, "--json"])));
  if (problems(plan)) return note(p, (how === "replace" ? "Cannot replace them now:\n\n" : "Cannot allow the removals now:\n\n") + problems(plan));
  const chk = plan.check || {}, w = plan.would || {}, rm = chk.removals || {};
  // what the copy there holds now; the pause as it was found, without a new look
  const x = Object.assign({}, syncPaused(p) || plan.paused || {}, chk.pause || {});
  const aside = `in ${plan.aside || "~/.aht/remote/replaced/"}`;
  const warned = (plan.warnings || []).map((t) => "\n\n⚠ " + sentence(t).trim()).join("");
  // what Replace Them removes there, by name; over the limit, it allows that too
  const gone = how === "replace" ? removalsOf(plan) : null, allow = gone && gone.over ? ["--allow-removals"] : [];
  const removes = gone ? `\n\nOn ${to}, this sync removes ${removalsCounted(gone)}, set aside there first:` + listed({ files: gone.files, removed: gone.removed })
    + (allow.length ? "\n\nThat is more than aht removes without asking, so Replace Them allows these removals too, once." : "") : "";
  let title, body, ok;
  if (how === "removals") {
    const n = w.remove != null ? w.remove : x.removed, total = w.total != null ? w.total : x.total;
    [title, ok] = [`Remove ${n ? plural(n, "file") : "the files"} from the copy on ${to}?`, "Allow the Removals"];
    body = `${n === 1 ? "It is" : "They are"} gone here, so this sync removes ${n === 1 ? "it" : "them"} there too, once${n && total ? ` (${n} of the ${total} files there)` : ""}. `
      + `${n === 1 ? "It is" : "They are"} set aside on ${to} first, ${aside}, not deleted.` + listed({ files: rm.files || filesIn(x), removed: n }) + warned;
  } else if (x.reason === "other-folder") {
    const n = w.replace || x.total;
    [title, ok] = [`Replace what is in the folder on ${to}?`, "Replace Them"];
    body = `The ${n ? plural(n, "file") : "files"} now in that folder on ${to} ${n === 1 ? "is" : "are"} set aside there first, ${aside}, not deleted. `
      + `Then “${name}” is copied there and kept in sync.` + listed(x) + removes + warned;
  } else {
    const now = chk.changes && counted(chk.changes) ? chk.changes : x, c = counted(now);
    [title, ok] = [`Replace the work on ${to} with this copy?`, "Replace Them"];
    body = `This sync makes the copy on ${to} the same as this one, once. The work done there${c ? ` (${c})` : ""} is set aside on ${to} first, ${aside}, not deleted:`
      + listed(now) + removes + warned + "\n\nTo keep that work instead, use Bring Them Here.";
  }
  if (!(await confirmIt(title, body, ok))) return;
  const d = await busy(`syncing ${name} with ${to}…`, () =>
    job(["mirror", p.real_path, flag, ...allow, "--apply", "--json"], "syncing", true).then((a) => a.json || { error: ((a.err || "") + (a.out || "")).trim() || null }));
  const row = (d.mirrored || [])[0] || {};
  note(p, problems(d) ? (how === "replace" ? "Not replaced:\n\n" : "The removals were not allowed:\n\n") + problems(d)
    : (how === "replace" ? `Replaced: what was there is set aside on ${to}, ${aside}.`
      : `Allowed: ${row.removed ? plural(row.removed, "file") : "what the sync"} removed there ${row.removed ? "are" : "is"} set aside on ${to}, ${aside}.`)
      + (syncedAfter(d, to) || (d.applied ? ` The copy on ${to} is the same as this one again.` : "")));
  refresh();
}
/** On the other machine: "Copy kept in sync from mac".  Work done in it
 * here is not overwritten: mac's next sync pauses and asks there.  Keep in
 * sync from here back to mac is refused for it (the core says so). */
function copyLine(c, p) {
  const m = c.from, at = c.since || c.at, since = at ? `, since ${clock(at)}` : "";
  // the project of a PC that aht cannot ask: no Send Back; it goes back there
  // (one that answers takes Send Back as any machine does)
  if (sendsBack(c) && pcHomeMute(c)) {
    const pc = c.remote || m, r = remoteRow(c.remote);
    return h("div", { class: "row copyof" }, h("span", { class: "badge", text: c.kind === "brought" ? `Brought here from ${m}` : `Handed over from ${m}` }),
      h("span", { class: "dim small grow", text: r && r.answers_why ? `Take it back on ${pc}; there is no Send Back from here. ${pcWhy(r)}`
        : `Take it back on ${pc}. aht cannot ask a PC, so there is no Send Back from here.` }),
      helpBtn(PC_SETUP));
  }
  // `kind`: "sync" (Keep in sync on that machine), "handover" (handed over
  // here), "brought" (Bring Here) or "returned" (it went back)
  const [label, more] = {
    sync: [`Copy kept in sync from ${m}`, `${m} sends its changes here${since}. Work done in it here is not overwritten: ${m}'s next sync pauses and asks there.`],
    handover: [`Handed over from ${m}`, `It goes back when you send it back, or when ${m} takes it back.`],
    brought: [`Brought here from ${m}`, `It is marked on ${m} as being here${since}. Send Back returns your work to ${m}.`],
    returned: [`A copy of a project that went back to ${m}`, null],
  }[c.kind || "sync"] || [`Copy from ${m}`, null];
  return h("div", { class: "row copyof" }, h("span", { class: "badge", text: label }),
    more ? h("span", { class: "dim small grow", text: more }) : null,
    p && sendsBack(c) && noName(c) ? h("span", { class: "warn small", text: `Send Back needs ${m} in the Machines tab: add it there first.` }) : null,
    p && sendsBack(c) ? h("button", { class: "small", text: `Send Back to ${c.remote || m}…`, disabled: !!p.handing || noName(c), onclick: () => sendBack(p) }) : null);
}
/** Stop Syncing: Keep in sync goes off; the copy there stays as it is. */
async function stopSyncing(p) {
  const to = p.mirror, x = syncPaused(p) || {};
  note(p, null);
  const r = await busy("turning Keep in sync off…", () => run(["mirror", p.real_path, "--off"]));
  note(p, r.ok ? `Keep in sync with ${to} is off. The copy on ${to} stays as it is${x.reason === "changed" ? ", with the work done there" : ""}.`
    : "Keep in sync was not turned off:\n\n" + ((r.err + r.out).trim() || "aht gave no answer."));
  refresh();
}

// A handover that did not finish (`handing`: the link dropped, or a machine
// slept): the core finishes it or undoes it once the other machine answers
// (at its notices check, or at once with Check Now); Release lets the
// project go on here without it.  `state`: "running" (it runs right now),
// "checking" or "unreachable"; `release`: an hour went by without an answer.
function handing(p) {
  const g = p.handing && typeof p.handing === "object" ? p.handing : {};
  return { to: g.remote || g.holder || g.host || "the other machine", state: g.state || "checking", error: g.error || "",
    silent: g.unreachable_since, release: !!g.release, there: g.driven_by === "there" || p.away_driven_by === "there", since: g.since };
}
/** The machine that brings a project there drives it (mark-away, or unmark
 * when it fails); aht here does not ask it.  The
 * notices check offers Release an hour after it began (the core's
 * HANDING_RELEASE_AFTER): "aht waits for pc; Release is offered after an
 * hour (at 15:10)." */
function waitsFor(g) {
  const t = typeof g.since === "number" ? g.since * 1000 : Date.parse(g.since || "");
  return `aht waits for ${g.to}; Release is offered after an hour${isNaN(t) ? "" : ` (at ${clock((t + 3600e3) / 1000)})`}.`;
}
const sentence = (t) => { t = String(t || "").trim(); return t ? t[0].toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? " " : ". ") : ""; };
function handingBanner(p) {
  const g = handing(p);
  if (S.moving === p.real_path) return null;          // this window is handing it over right now
  if (g.state === "running") {
    return h("div", { class: "callout row" }, h("div", { class: "grow" }, h("strong", { text: `Handover to ${g.to} under way` }),
      h("div", { class: "small", text: "This note goes when it is done." })));
  }
  const gone = g.state === "unreachable";
  // the other machine began bringing it there (Bring Here at that machine)
  if (g.there) {
    return h("div", { class: "callout row" },
      h("div", { class: "grow" }, h("strong", { text: `${g.to} began bringing this project there${g.since ? " at " + clock(g.since) : ""}` }),
        h("div", { class: "small", text: `${sentence(g.error)}When ${g.to} finishes, the project shows as on ${g.to}. `
          + (g.release ? `If it does not, Release lets the project go on here; what was copied to ${g.to} stays there.` : waitsFor(g)) })),
      // no Check Now: there is nobody here to ask
      h("button", { class: g.release ? "small primary" : "small", text: "Release…", onclick: () => release(p) }),
      helpBtn("Hand a project over"));
  }
  return h("div", { class: "callout row" },
    h("div", { class: "grow" },
      h("strong", { text: gone ? `Handover to ${g.to} did not finish` : `Handover to ${g.to} unfinished: checking…` }),
      h("div", { class: "small", text: gone
        ? `${g.to} has not answered${g.silent ? " since " + clock(g.silent) : ""}. ` + (g.release
          ? `Release lets the project go on here; what was done on ${g.to} stays there.` : "aht asks again every minute.")
        : `${sentence(g.error)}aht asks ${g.to} within a few minutes whether the session there started, then finishes the handover or undoes it.` })),
    h("button", { class: "small", text: "Check Now", onclick: () => checkHanding(p) }),
    h("button", { class: g.release ? "small primary" : "small", text: "Release…", onclick: () => release(p) }),
    helpBtn("Hand a project over"));
}
/** Check Now: Take Back's dry run, which first settles an unfinished
 * handover with the other machine. */
async function checkHanding(p) {
  const { to } = handing(p), name = base(p.real_path);
  note(p, null);
  const d = await busy(`asking ${to}…`, () => job(["reclaim", p.real_path, "--json"], `asking ${to}`).then((a) => a.json || {}));
  await refresh();
  const q = S.projects.find((x) => x.real_path === p.real_path) || {};
  if ((d.checked || []).length) return note(p, d.checked.join("\n"));
  if (q.handing) {
    const g = handing(q);
    return note(p, g.state === "running" ? `The handover to ${to} is under way right now.`
      : g.there ? `${to} has not finished bringing ${name} there. ${waitsFor(g)}`
      : `${to} did not answer${g.error ? ` (${g.error})` : ""}. aht asks again every minute.`);
  }
  note(p, q.away ? `The handover of ${name} to ${to} finished.` : `The handover of ${name} to ${to} did not finish. The project stays here.`);
}
/** Release: the project counts as here again, as it is; the copy on the
 * other machine is left as it is (`aht reclaim --release`). */
async function release(p) {
  let to = p.handing ? handing(p).to : p.away_remote || p.away || "the other machine";
  const since = (p.handing || {}).since || p.away_since;
  const name = base(p.real_path);
  note(p, null);
  const a = await busy(`checking ${name}…`, () => run(["reclaim", p.real_path, "--release", "--json"]));
  const plan = a.json || {};
  if (problems(plan) || !a.json) return note(p, "Cannot be released now:\n\n" + (problems(plan) || (a.out + a.err).trim() || "aht gave no answer."));
  const lose = plan.would_lose || {}, from = lose.since || since;
  if (plan.remote) to = plan.remote;
  // what stays there: the files changed there and the conversation held
  // there (its history); each a count, or null when that machine did not
  // answer
  const count = (x) => (Array.isArray(x) ? x.length : x === true ? 1 : x === false ? 0 : x);
  const n = count(lose.files), conv = count(lose.history);
  const at = from ? ` since ${clock(from)}` : "";
  const stays = [n ? plural(n, "file") : null, conv ? "the conversation" : null].filter(Boolean).join(" and ");
  // Keep in sync with that machine pauses (`pauses_sync`: its name), so no
  // sync replaces the copy there
  const pauses = plan.pauses_sync;
  let body = `${name} counts as here again, with its files here as they are. The copy on ${to} is not touched.\n\n`;
  body += n === 0 && conv === 0 ? `Nothing changed on ${to}${at}, so nothing stays behind there.`
    : `The work done on ${to}${at} stays on ${to}${stays ? ": " + stays : ""}. It does not come here.`;
  if (Array.isArray(lose.files) && n) body += "\n" + lose.files.slice(0, 6).map((x) => "• " + x).join("\n") + (n > 6 ? `\n… and ${n - 6} more` : "");
  if (pauses) body += `\n\nKeep in sync with ${pauses} will be paused, so the copy there stays as it is. You can turn it back on later.`;
  if (!(await confirmIt(`Release “${name}” from ${to}?`, body, "Release"))) return;
  const r = await busy(`releasing ${name}…`, () => run(["reclaim", p.real_path, "--release", "--apply", "--json"]));
  const d = r.json || {};
  // the pause as the core recorded it, not as the dry run expected
  note(p, !d.released ? "Not released:\n\n" + (problems(d) || (r.out + r.err).trim() || "aht gave no answer.")
    : `Released: ${name} is here again. ` + (d.pauses_sync ? `Keep in sync with ${d.pauses_sync} is paused, so the copy there stays as it is.`
      : `The copy on ${to} stays as it is.`));
  refresh();
}

// ---- across systems: Bring Here and Send Back; where folders go ------------------------
// Four verbs between any two of Mac, Windows and Linux.  "Home" keeps the
// project's record; the "holder" works on it meanwhile.  Hand Over and Take
// Back run at home; Bring Here and Send Back run at the holder, and need aht
// at home, which must be a machine aht can ask (not a PC that does not
// answer).  A folder can sit
// at another path on each machine: `remotes.<name>.paths` says where.

const arr = (x) => (Array.isArray(x) ? x : []);
const spinner = (text) => h("p", { class: "dim" }, h("span", { class: "spin" }), text);
const sameDir = (a, b) => {
  const k = (x) => { const s = String(x || "").replace(/[\\/]+$/, ""); return ON_WINDOWS() ? s.replace(/\//g, "\\").toLowerCase() : s; };
  return k(a) === k(b);
};
/** A sentence with commands in it: in `backticks`, or the core's way, after
 * a colon and two spaces (up to three spaces or the end).  Each is shown as
 * code with a Copy button; one that ends in "…" (fill in the rest) is shown
 * only. */
function withCommands(text, cls) {
  const line = h("div", { class: (cls || "small") + " fix" });
  const cmd = (c) => [h("code", { text: c }), /…$/.test(c) ? null : [" ", h("button", { class: "small", text: "Copy", onclick: () => copyText(c) })]];
  const s = String(text), re = /`([^`]+)`|:\s{2,}((?:aht|git|sudo|ssh|brew) .*?)(?=\s{3,}|\.?$)/g;
  let at = 0, m;
  while ((m = re.exec(s))) {
    line.append(s.slice(at, m.index) + (m[1] === undefined ? ": " : ""), cmd(m[1] === undefined ? m[2] : m[1]));
    at = m.index + m[0].length;
  }
  line.append(s.slice(at));
  return line;
}
/** Blockers about where the folder goes: another folder in its place, a
 * live project there, or a folder outside every mapped one. */
const WHERE = /holds another folder|live project of its own|outside yours|remote paths/;
/** The core's words as a sentence: a capital first, unless it is aht's
 * own name. */
const said = (t) => (/^aht\b/.test(String(t || "")) ? String(t).trim() + (/[.!?]$/.test(String(t).trim()) ? "" : ".") : sentence(t).trim());
/** The core's one blocker for `names`, which namesPart says in full. */
const NAMES_BLOCKER = /^\d+ names? .* cannot hold \(/;
/** Why it cannot go ahead, each reason in the core's words, with the
 * commands they name to copy; `ways`: buttons past one of them.  When it is
 * about where the folder goes, the way to change that for `machine`. */
function blockedPart(d, machine, ways, title = "Not possible now") {
  // the names are listed by namesPart: not twice
  const named = arr(d.names).length > 0;
  const b = [...(d.blockers || []), ...(d.error ? [d.error] : [])].filter((x) => !(named && NAMES_BLOCKER.test(x)));
  if (!b.length) return null;
  const where = !!machine && b.some((x) => WHERE.test(x)), past = [].concat(ways || []).filter(Boolean);
  // the folder there (or here) holds something else: the core's own command
  // for it (`identity.fix`, whole and runnable), not one read out of its words
  const fix = d.identity && typeof d.identity === "object" && typeof d.identity.fix === "string" && d.identity.fix ? d.identity.fix : null;
  const own = fix ? b.find((x) => String(x).includes(fix)) || b.find((x) => /holds another folder|live project of its own/.test(x)) : null;
  const identityLine = (x) => {
    const s = String(x), at = s.lastIndexOf(fix);
    const words = (at < 0 ? s : s.slice(0, at)).trim(), rest = at < 0 ? "" : s.slice(at + fix.length).trim();
    const t = /^aht\b/.test(words) ? words : sentence(words).trim().replace(/[.:]\.$/, (m) => m[0]);
    return h("div", { class: "small fix" }, t + (/:$/.test(t) ? " " : " To use another place: "), h("code", { text: fix }), " ",
      h("button", { class: "small", text: "Copy", onclick: () => copyText(fix) }), rest && rest !== "." ? " " + rest : "");
  };
  return h("div", { class: "callout" }, h("strong", { text: title }),
    b.map((x) => (own && x === own ? identityLine(x) : withCommands(said(x)))),
    where || past.length ? h("div", { class: "row", style: "margin-top:6px" }, past,
      where ? h("button", { class: "small", text: `Where Projects Go on ${machine}…`, onclick: () => editPaths(machine) }) : null) : null);
}
/** The kinds of name Leave Them Out is for: a name Windows cannot hold
 * whatever else is in the folder.  Names that collide (capitals, Unicode
 * forms), a path too long or a link are not left out: their names are
 * ordinary ones (README.md), and handover_excludes counts in every project. */
const LEAVE_OUT = ["windows_char", "trailing", "reserved"];
/** Why Windows cannot hold a file named `part` (one part of a path), as the
 * core's _win_name_kind says it, or null. */
function winNameKind(part) {
  if (/[<>:"|?*\\\x00-\x1f]/.test(part)) return "windows_char";
  if (/[. ]$/.test(part)) return "trailing";
  if (/^(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(\..*)?$/i.test(part)) return "reserved";
  return null;
}
/** The part of `path` (the core's key: parts joined with "/") that is the
 * problem of `kind`: the first one Windows cannot hold, as the core's
 * _cannot_hold finds it; null when none is. */
function badPart(path, kind) {
  const parts = String(path).split("/").filter(Boolean);
  return parts.find((x) => winNameKind(x) === kind) || null;
}
/** Names the disk that receives cannot hold (`names`: [{kind, text, count,
 * names}], each of `names` one name or the names that collide), ten of each
 * kind at most, and the fix: rename them, or leave them out of what moves
 * (`handover_excludes`; Leave Them Out adds only the part of each path that
 * is the problem, then `again()`). */
function namesPart(d, where, again) {
  const ns = arr(d.names).filter((x) => x && (x.count || arr(x.names).length));
  if (!ns.length) return null;
  const rows = [], bad = [];
  for (const x of ns) {
    const list = arr(x.names).slice(0, 10), why = x.text || x.kind || "";
    for (const n of list) {
      rows.push(h("li", {}, h("span", { class: "mono", text: [].concat(n).join("  and  ") }), h("span", { class: "dim", text: " — " + why })));
      if (LEAVE_OUT.includes(x.kind)) bad.push(...[].concat(n).map((y) => badPart(y, x.kind)).filter(Boolean));
    }
    const more = (Number(x.count) || list.length) - list.length;
    if (more > 0) rows.push(h("li", { class: "dim", text: `… and ${more} more: ${why}` }));
  }
  // as fnmatch patterns that match only that name; the ones not set yet
  const had = arr(S.config.handover_excludes);
  const pats = [...new Set(bad.map((n) => n.replace(/[[\]*?]/g, (c) => `[${c}]`)))].filter((p) => !had.includes(p));
  const out = async () => {
    if (!(await confirmIt("Leave these names out?", `${pats.length === 1 ? "This entry goes" : `These ${pats.length} entries go`} into the setting handover_excludes:\n\n`
      + pats.map((p) => "• " + p).join("\n")
      + `\n\nA file or folder with ${pats.length === 1 ? "this name" : "one of these names"} stays on this machine, in every project: no handover, Bring Here, Send Back or Keep in sync moves it. Settings has the list.`, "Leave Them Out"))) return;
    await setConfig("handover_excludes", [...had, ...pats]);
    if (again) again();
  };
  return h("div", { class: "callout names" }, h("strong", { text: `Names ${where} cannot hold` }),
    h("ul", { class: "files" }, rows),
    h("div", { class: "row", style: "margin-top:6px" }, h("span", { class: "small grow", text: "Rename them, or leave them out of what moves between your machines." }),
      pats.length ? h("button", { class: "small", text: "Leave Them Out…", onclick: out }) : null));
}
/** The system of the machine on the other side, from a dry run. */
const farSystem = (d) => d.system || (d.there && typeof d.there === "object" ? d.there.system : null) || null;
/** The lines a `.gitattributes` gets when a git project without one
 * crosses to or from Windows, when the core does not name them. */
const GITATTRIBUTES = ["* text=auto", "*.sh text eol=lf", "*.bat text eol=crlf", "*.cmd text eol=crlf", "*.ps1 text eol=crlf"];
/** git across systems, from a dry run's `git` row ({is_git, gitattributes,
 * suggest, env, how}; Pick Up's {here, there} is another thing): the lines
 * aht suggests for a .gitattributes it never writes, with Copy; and how to
 * give git the settings aht's session there gets, in your own terminal. */
function gitattrPart(d) {
  const g = d.git && typeof d.git === "object" && !("here" in d.git) ? d.git : {};
  const old = d.gitattributes;        // an earlier sample's form
  const lines = arr(g.suggest).length ? g.suggest : !old ? [] : arr(old).length ? old : arr(old.lines).length ? old.lines : GITATTRIBUTES;
  if (!lines.length && !g.how) return null;
  const text = lines.join("\n") + "\n";
  return h("div", { class: "box git gitattr" },
    lines.length ? [h("strong", { text: "This project has no .gitattributes" }),
      h("div", { class: "small", text: "It crosses between Windows and another system, where git can see every line of a file as changed. These lines, in a file named .gitattributes at the top of the project, keep each file's line endings steady. aht does not write it." }),
      h("div", { class: "row top" }, h("pre", { class: "grow", style: "margin:4px 0", text: text.trim() }),
        h("button", { class: "small", text: "Copy", onclick: () => copyText(text) }))] : null,
    g.how ? withCommands(sentence(g.how).trim()) : null);
}
/** What a return across systems leaves as it was (`eol_only`: files that
 * differ only in line endings, not taken; `eol_kept`: changed files whose
 * line endings went back to how they were at home; `unsafe_names`: [{there,
 * kept_as}], files whose name home cannot hold, set aside under a safe
 * name), then the .gitattributes hint.  `home`: "here", or that machine. */
function crossNotes(d, home) {
  const here = home === "here", at = here ? "here" : `on ${home}`;
  const fold = (head, files, fmt) => (files.length ? h("details", { class: "small eol" }, h("summary", { text: head }),
    h("ul", { class: "files" }, files.slice(0, 50).map((f) => h("li", { class: "mono", text: fmt ? fmt(f) : String(f) })),
      files.length > 50 ? h("li", { class: "dim", text: `… and ${files.length - 50} more` }) : null)) : null);
  const eol = arr(d.eol_only), kept = arr(d.eol_kept), odd = arr(d.unsafe_names);
  return [
    fold(`${plural(eol.length, "file")} ${eol.length === 1 ? "differs" : "differ"} only in line endings: ${here ? "the ones here stay" : home + "'s stay"}.`, eol),
    fold(`${plural(kept.length, "changed file")}: line endings kept as they were ${at}.`, kept),
    fold(`Kept aside ${at}: ${plural(odd.length, "file")} whose name ${here ? "this machine" : home} cannot hold.`, odd,
      (x) => (x && typeof x === "object" ? `${x.there || x.name}  →  ${x.kept_as || ""}` : String(x))),
    gitattrPart(d)];
}
/** The core's other lines for this crossing (`notes`: "2 scripts lose their
 * executable mark here", say) and its warnings. */
const sayLines = (d) => [arr(d.notes).map((t) => h("p", { class: "small", text: sentence(t).trim() })),
  arr(d.warnings).map((w) => h("p", { class: "warn small", text: "⚠ " + w }))];

/** "On pc since 14:10 (brought there from pc). Send it back from pc." with
 * [Release…]: a project of this machine's that comes back from there.  One
 * handed over to a PC from here: no session started there, and the PC's
 * tray offers Continue here; Take Back fetches it while the PC answers. */
function awayLine(p, a) {
  const at = a.since ? " since " + clock(a.since) : "";
  if (a.pc && !a.there) {
    return h("div", { class: "row awayrow" },
      h("span", { class: "grow", text: `On ${a.name}${at}: continue it on the PC (its tray offers Continue here).`
        + (a.take ? "" : ` ${pcWhy(remoteRow(p.away_remote))}`) }),
      a.take ? null : h("button", { class: "small", text: "Release…", onclick: () => release(p) }), helpBtn(a.take ? "Hand a project over" : PC_SETUP));
  }
  return h("div", { class: "row awayrow" },
    h("span", { class: "grow", text: `On ${a.name}${at}${a.agent ? `, in ${a.agent}` : ""}${a.there ? ` (brought there from ${a.name})` : ""}. Send it back from ${a.name}${a.take ? ", or take it back here" : ""}.` }),
    h("button", { class: "small", text: "Release…", onclick: () => release(p) }), helpBtn("Hand a project over"));
}

/** Bring Here from M, first step: the projects aht keeps on M (`bring
 * --from M --list --json`: rows with path, here_path, can_bring, why_not,
 * state, away, open, session), each with Bring Here… (bringHere).  One no
 * mapped folder here reaches (`here_error`) can still come: the sheet's
 * Another Folder… picks where. */
async function bringList(machine) {
  const s = sheet(`Bring a project here from ${machine}`, "Hand a project over", 760);
  let d = null, filter = "";
  const load = async () => {
    d = null; paint();
    const got = await dryRun(["bring", "--from", machine, "--list", "--json"]);
    if (!s.body.isConnected) return;
    d = got; paint();
  };
  const row = (r) => {
    const path = r.path || "";
    const away = r.away && typeof r.away === "object" ? r.away.holder || r.away.remote || "another machine" : r.away || null;
    const can = "can_bring" in r ? !!r.can_bring || (!!r.here_error && r.why_not === r.here_error) : !away && !!path;
    const state = away ? `on ${away}` : { handing: "moving", gone: "gone", copy: "a copy" }[r.state]
      || (r.open === "idle" ? "open there" : r.open || "");
    const sess = r.session && typeof r.session === "object" ? r.session : {};
    const facts = [sess.title ? `“${sess.title}”` : null, sess.updated ? "last used " + ago(sess.updated) : null].filter(Boolean).join(" · ");
    return h("div", { class: "s" }, h("div", { class: "grow" },
      h("div", { class: "row" }, h("strong", { text: r.name || base(path) }),
        state ? h("span", { class: "badge " + (r.open === "working" ? "working" : r.open === "waiting" ? "waiting" : ""), text: state }) : null),
      h("div", { class: "dim small mono", style: "overflow-wrap:anywhere", text: path + (r.here_path ? `  →  ${r.here_path}` : "") }),
      facts ? h("div", { class: "dim small", text: facts }) : null,
      r.why_not ? withCommands(said(r.why_not), "small warn") : null),
    h("button", { class: "small", text: "Bring Here…", disabled: !can, onclick: () => bringHere(machine, path) }));
  };
  const paint = () => {
    const b = clear(s.body), f = clear(s.foot);
    f.append(h("button", { text: "Ask Again", disabled: !d, onclick: load }), h("span", { class: "spacer" }), h("button", { text: "Close", class: "primary", onclick: closeSheet }));
    if (!d) return b.append(spinner(`Asking ${machine}…`));
    const rows = arr(d.projects);
    if (problems(d)) {
      b.append(h("div", { class: "callout" }, h("strong", { text: rows.length ? "Not possible now" : `aht could not ask ${machine}` }),
        [...arr(d.blockers), ...(d.error ? [d.error] : [])].map((x) => withCommands(said(x)))));
      if (!rows.length) return;
    }
    if (!rows.length) return b.append(h("p", { class: "dim", text: `aht on ${machine} keeps no project that could come here.` }));
    b.append(h("p", { class: "dim small", text: `A project comes here with its files and Claude Code's history. On ${machine} it is marked as being here, and its own copy stays as it is. When you are done, Send Back returns your work to ${machine}.` }));
    const list = h("div", { class: "sessions bringlist" });
    const fill = () => clear(list).append(rows.filter((r) => !filter || String(r.path || "").toLowerCase().includes(filter)).map(row));
    if (rows.length > 8) {
      b.append(h("input", { type: "search", placeholder: "Filter projects", style: "width:100%;margin-bottom:6px",
        oninput: (e) => { filter = e.target.value.toLowerCase(); fill(); } }));
    }
    b.append(list);
    fill();
  };
  paint();
  load();
}

/** What comes, in counts: a whole copy (`files`, `bytes`, `history_bytes`;
 * Bring Here's), or Take Back's plan ({project, history}: take, new, delete,
 * conflict, kept); `where`: where the changes were made, `other`: the other
 * side. */
function planFacts(plan, where, other) {
  if (!plan || typeof plan !== "object") return [];
  if ("files" in plan || "bytes" in plan) {
    return [["Files", `${plural(plan.files || 0, "file")} (${bytes(plan.bytes)})`],
      plan.history_bytes != null ? ["History", `Claude Code's, ${bytes(plan.history_bytes)}`] : null].filter(Boolean);
  }
  const n = plan.project || {}, hs = plan.history || {};
  return [["Files", `${n.take || 0} changed, ${n.new || 0} new, ${n.delete || 0} removed ${where}; ${n.kept || 0} changed only ${other}`],
    hs.take || hs.new ? ["History", `${hs.take || 0} continued, ${hs.new || 0} new`] : null].filter(Boolean);
}
const factsGrid = (rows) => (rows.length ? h("div", { class: "facts" }, rows.map(([k, v]) => [h("span", { class: "dim", text: k }), typeof v === "string" ? h("span", { text: v }) : v])) : null);

/** Bring Here from M: the dry run (`bring <path there> --from M --json`)
 * in a sheet: where it comes from and goes, what comes, what blocks it and
 * how past it, what stays there, then [Bring Here].  The session opens here
 * in a new terminal; nothing runs until you type.  `o.here`: the folder
 * here to use (`--here`: the project's folder itself). */
async function bringHere(machine, there, o = {}) {
  const name = base(there);
  // agent: the agent that goes on here (Agent here): Claude Code's own
  // session, or another agent that starts with the summary (`--agent X`)
  const st = { here: o.here || null, idle: false, d: null, agent: "claude" };
  const s = sheet(`Bring “${name}” here from ${machine}`, "Hand a project over", 760);
  const opts = () => [...(st.here ? ["--here", st.here] : []), ...(st.idle ? ["--allow-idle"] : []),
    ...(st.agent !== "claude" ? ["--agent", st.agent] : [])];
  const look = async () => {
    st.d = null; paint();
    const d = await dryRun(["bring", there, "--from", machine, ...opts(), "--json"]);
    if (!s.body.isConnected) return;
    st.d = d; paint();
  };
  // another folder here: the project goes into the folder chosen
  const change = async () => {
    const dir = await pickFolder(`Choose the folder to put “${name}” in`);
    if (!dir || !s.body.isConnected) return;
    st.here = dir.replace(/[\\/]+$/, "") + (ON_WINDOWS() ? "\\" : "/") + name;
    look();
  };
  const go = async () => {
    closeSheet();
    const a = await busy(`bringing ${name} here…`, () => job(["bring", there, "--from", machine, ...opts(), "--apply", "--json"], "bringing it here", true));
    const d = a.json || {};
    const failed = problems(d) || (a.ok && d.applied ? null : ((a.out || "") + (a.err || "")).trim() || "aht gave no answer.");
    await refresh();
    const here = d.here_path || (st.d || {}).here_path || st.here;
    const p = S.projects.find((x) => sameDir(x.real_path, here));
    const got = d.fetched || {}, line = d.command_line || "", other = st.agent !== "claude";
    const label = AGENTS[st.agent] || st.agent;
    // Kimi below never-ask opened without reading the summary: the first message to paste
    const first = !failed && st.agent === "kimi" ? farFirst(d) : null;
    const text = failed ? "It did not come here:\n\n" + failed
      : `Brought here from ${machine}${here ? ` into ${here}` : ""}${got.files != null ? `: ${plural(got.files, "file")} (${bytes(got.bytes)})` : ""}. On ${machine} it is marked as being here.\n\n`
        + (d.opened && other ? `${label} is open in a new terminal${first ? "." : ": it reads aht's summary of the work as its first turn."}`
          : d.opened ? "Its session is open in a new terminal: nothing runs until you type."
          : line ? `No terminal window opened. Run this in a terminal to go on:\n\n${line}` : "")
        + (d.set_aside ? `\n\nWhat was in that folder before is kept in ${d.set_aside}.` : "")
        + (arr(d.warnings).length ? "\n\n" + d.warnings.map((w) => "⚠ " + w).join("\n") : "");
    if (!p) return tell(failed ? "Not brought here" : "Brought here", text + (first ? "\n\nPaste this into Kimi Code as your first message:\n\n" + first : ""));
    S.tab = "projects"; S.selection = p.real_path; drawTop();
    note(p, text, d.set_aside || null, first ? [firstPromptPart(first)] : undefined);
  };
  const paint = () => {
    const b = clear(s.body), f = clear(s.foot), d = st.d;
    const cancel = h("button", { text: "Cancel", onclick: closeSheet });
    if (!d) { b.append(spinner(`Asking ${machine}…`)); f.append(h("span", { class: "spacer" }), cancel); return; }
    const why = problems(d), plan = d.plan || {};
    const wrap = h("div", { class: "stack" });
    b.append(wrap);
    wrap.append(factsGrid([
      [`On ${machine}`, h("span", { class: "mono", text: d.there_path || there })],
      ["Here", h("span", {}, h("span", { class: "mono", text: d.here_path || st.here || "—" }), " ",
        h("button", { class: "small", text: "Another Folder…", onclick: change }))]]));
    // Agent here: Claude Code's own session (no tokens), or another agent
    // that starts with the summary (one turn); its own dry run says what
    // stops it and the level it starts in
    const agents = agentsHere();
    if (agents.length > 1 || st.agent !== "claude") {
      wrap.append(h("div", { class: "stack agent-here" },
        agentPicker("Agent here", agents.includes(st.agent) ? agents : agents.concat([st.agent]), st.agent, (a) => { st.agent = a; look(); }),
        h("div", { class: "dim small tokens", text: agentCost(st.agent, null, false, d) })));
    }
    // an idle session there blocks, unless allowed: if anyone types into it
    // later, Send Back keeps both versions
    const idle = !st.idle && arr(d.blockers).some((x) => /--allow-idle/.test(x));
    if (why) {
      wrap.append(blockedPart(d, machine, idle ? h("button", { class: "small", text: "Bring It Anyway",
        onclick: () => { st.idle = true; look(); } }) : null));
      if (idle) wrap.append(h("p", { class: "dim small", text: `Bring It Anyway leaves the idle session on ${machine} as it is. If anyone types into it later, Send Back keeps both versions.` }));
    }
    wrap.append(namesPart(d, "this computer", look));
    if (!why) {
      const sess = d.session && typeof d.session === "object" ? d.session : {};
      wrap.append(factsGrid([...planFacts(plan, `on ${machine}`, "here"),
        plan.set_aside ? ["Here", `${plural(plan.set_aside, "file")} in the folder here ${plan.set_aside === 1 ? "is" : "are"} set aside first`] : null,
        st.agent !== "claude" ? ["Session", `${AGENTS[st.agent] || st.agent} starts here in a new terminal with aht's summary of the work${sess.title ? ` (“${sess.title}”)` : ""}`]
          : ["Session", sess.id ? `${sess.title ? `“${sess.title}” — ` : ""}opens here in a new terminal; nothing runs until you type` : "none yet"]].filter(Boolean)));
      // the level its session opens in here, like it ran there; or the level
      // the agent chosen starts in
      const from = sess.agent || (st.agent === "claude" ? d.agent : null) || "claude";
      if (sess.id || st.agent !== "claude") {
        wrap.append(permPart(d, st.agent === "claude" ? sess.agent || d.agent || "claude" : st.agent,
          { agent: from, leaving: (a) => `the ${a ? a + " " : ""}session on ${machine}` }));
      }
      if (st.idle) wrap.append(h("p", { class: "small", text: `The idle session on ${machine} stays as it is. If anyone types into it later, Send Back keeps both versions.` }));
      wrap.append(h("p", { class: "small", text: `On ${machine} the project is marked as being here; its own copy stays as it is. Send Back returns your work when you are done.` }));
    }
    // what does not come, or comes with less
    const modes = arr(d.modes_lost);
    wrap.append(modes.length ? h("details", { class: "small eol" }, h("summary", { text: `${plural(modes.length, "script")} ${modes.length === 1 ? "loses its" : "lose their"} “executable” mark here; ${modes.length === 1 ? "it gets it" : "they get it"} back on ${machine}.` }),
      h("ul", { class: "files" }, modes.slice(0, 50).map((x) => h("li", { class: "mono", text: x })))) : null,
    arr(d.other_histories).map((a) => h("p", { class: "small", text: `${AGENTS[a] || a}'s history stays on ${machine}; only Claude Code's comes.` })),
    !why && d.session && d.session.id && plan.file_history === false ? h("p", { class: "dim small", text: `Claude Code's /rewind snapshots stay on ${machine}: the folder's path differs here.` }) : null,
    crossNotes(d, machine), sayLines(d));
    f.append(h("span", { class: "spacer" }), cancel, h("button", { class: "primary", text: "Bring Here", disabled: !!why, onclick: go }));
  };
  paint();
  look();
}

/** Send Back to M, at the holder: M (home) plans the return against what
 * left it (`send-back <path> --json`, Take Back's words), then [Send Back]
 * pushes the files and M places them; what they replace is set aside there.
 * Changed on both: Keep Both (M's stays, this one goes next to it: the
 * default) or the versions from here (`--prefer here`: M's are set aside
 * there).  A newer Claude Code wrote the history here: Send Back Anyway
 * (`--ignore-version`). */
async function sendBack(p) {
  const name = base(p.real_path), c = copyOf(p) || {};
  let to = c.remote || c.from || "the other machine";
  if (S.projects.includes(p)) note(p, null);
  const st = { d: null, ignore: false, prefer: null };
  const s = sheet(`Send “${name}” back to ${to}`, "Hand a project over", 760);
  const look = async () => {
    st.d = null; paint();
    const d = await dryRun(["send-back", p.real_path, ...(st.ignore ? ["--ignore-version"] : []), "--json"]);
    if (!s.body.isConnected) return;
    st.d = d;
    if (d.remote && d.remote !== to) { to = d.remote; s.head.querySelector("h1").textContent = `Send “${name}” back to ${to}`; }
    paint();
  };
  const go = async () => {
    const flags = [...(st.ignore ? ["--ignore-version"] : []), ...(st.prefer ? ["--prefer", st.prefer] : [])];
    closeSheet();
    const a = await busy(`sending ${name} back to ${to}…`, () => job(["send-back", p.real_path, ...flags, "--apply", "--json"], "sending it back", true));
    const d = a.json || {};
    const failed = problems(d) || (a.ok && d.applied ? null : ((a.out || "") + (a.err || "")).trim() || "aht gave no answer.");
    const both = arr(((d.done || {}).project || {}).conflicts).map((x) => (x && typeof x === "object" ? x.their_version || x.file : x));
    const text = failed ? "It was not sent back:\n\n" + failed
      : `Sent back to ${to}: the project is on ${to} again, with the work done here. Whatever it replaced there is set aside on ${to}, not deleted${d.set_aside ? ` (${d.set_aside})` : ""}. This folder stays here as it is.`
        + (both.length ? `\n\nChanged on both machines, kept twice on ${to}:\n` + both.slice(0, 6).map((x) => "• " + x).join("\n") : "")
        // another agent worked here: what it did is summed up for Claude Code there
        + (d.catchup && d.catchup.agent ? `\n\nWhat ${AGENTS[d.catchup.agent] || d.catchup.agent} did here is summed up for the Claude Code session on ${to}.` : "");
    await refresh();
    const q = S.projects.find((x) => sameDir(x.real_path, p.real_path));
    if (q) note(q, text); else tell(failed ? "Not sent back" : "Sent back", text);
  };
  const paint = () => {
    const b = clear(s.body), f = clear(s.foot), d = st.d;
    const cancel = h("button", { text: "Cancel", onclick: closeSheet });
    if (!d) { b.append(spinner(`Asking ${to}…`)); f.append(h("span", { class: "spacer" }), cancel); return; }
    const why = problems(d);
    const wrap = h("div", { class: "stack" });
    b.append(wrap);
    wrap.append(factsGrid([["Here", h("span", { class: "mono", text: d.here_path || p.real_path })],
      [`On ${to}`, h("span", { class: "mono", text: d.there_path || "—" })]]));
    const newer = !st.ignore && arr(d.blockers).find((x) => /--ignore-version/.test(x));
    if (why) {
      wrap.append(blockedPart(d, to, newer ? h("button", { class: "small", text: "Send Back Anyway…", onclick: async () => {
        if (!(await confirmIt("Send it back anyway?", `${sentence(newer).trim()}\n\nUpdate Claude Code on ${to} before you continue the session there.`, "Send Back Anyway"))) return;
        st.ignore = true; look();
      } }) : null));
    }
    if (!why) {
      wrap.append(factsGrid(planFacts(d.plan, "here", `on ${to}`)));
      const both = Object.values(d.conflicts || {}).flat();
      if (both.length) {
        const pick = (v, text) => h("label", { class: "check" }, h("input", { type: "radio", name: "sb-prefer", checked: st.prefer === v,
          onchange: () => { st.prefer = v; } }), text);
        wrap.append(h("div", { class: "callout" }, h("strong", { text: "Changed on both machines" }),
          h("ul", { class: "files" }, both.slice(0, 10).map((x) => h("li", { class: "mono", text: String(x) })),
            both.length > 10 ? h("li", { class: "dim", text: `… and ${both.length - 10} more` }) : null),
          pick(null, `Keep both: ${to}'s version stays, the one from here goes next to it`),
          pick("here", `Use the versions from here: ${to}'s are set aside there`)));
      }
      wrap.append(h("p", { class: "small", text: `Then the project is on ${to} again, with your work. Whatever it replaces there is set aside on ${to}, not deleted. This folder stays here as it is.` }));
    }
    wrap.append(namesPart(d, to), crossNotes(d, to), sayLines(d));
    f.append(h("span", { class: "spacer" }), cancel, h("button", { class: "primary", text: "Send Back", disabled: !!why, onclick: go }));
  };
  paint();
  look();
}

/** Where a project in a folder here goes on a machine (`remotes.<name>.paths`):
 * "same", "home", or [here, there] pairs (tried first, longest first, then
 * the home folders). */
function pathsText(v) {
  if (v === "same") return "at the same paths as here";
  if (v === "home") return "at the same place in the home folder";
  if (arr(v).length) return arr(v).map((x) => `${x[0]} → ${x[1]}`).join(" · ") + "; else the same place in the home folder";
  return "set the first time a project goes there";
}
function pathsLine(name, r) {
  return h("div", { class: "row small paths" }, h("span", { class: "dim", text: "Folders there:" }),
    h("span", { class: "grow", text: pathsText(r.paths) }),
    h("button", { class: "small", text: "Change…", onclick: () => editPaths(name) }));
}
/** Where projects go on a machine (`remote paths NAME --json`), and the
 * changes, each at once: --home, --same, --add HERE THERE, --remove HERE. */
async function editPaths(name) {
  const s = sheet(`Where projects go on ${name}`, "Hand a project over", 640);
  let d = null, said = null;
  const load = async () => {
    const got = await dryRun(["remote", "paths", name, "--json"]);
    if (!s.body.isConnected) return;
    d = got; paint();
  };
  const change = async (args) => {
    const a = await busy("changing it…", () => run(["remote", "paths", name, ...args, "--json"]));
    const x = a.json || {};
    said = problems(x) || (a.ok ? null : ((a.err || "") + (a.out || "")).trim() || "aht gave no answer.");
    if (!s.body.isConnected) return;
    if (!said && "paths" in x) { d = x; paint(); } else await load();
    refresh();
  };
  const paint = () => {
    const b = clear(s.body), f = clear(s.foot);
    f.append(h("span", { class: "spacer" }), h("button", { class: "primary", text: "Done", onclick: closeSheet }));
    if (!d) return b.append(spinner("Reading it…"));
    if (!("paths" in d) && problems(d)) return b.append(h("p", { class: "warn small", style: "white-space:pre-wrap", text: problems(d) }));
    const v = d.paths, pairs = arr(v);
    // an example from the two home folders (`here_home`, `there_home`),
    // each spelled its system's way
    const farWin = (d.system || (((S.status.handover || {}).remotes || {})[name] || {}).system) === "Windows";
    const hereWin = d.here_system ? d.here_system === "Windows" : ON_WINDOWS();
    const join = (root, win) => String(root).replace(/[\\/]+$/, "") + (win ? "\\code\\shop" : "/code/shop");
    const ex = d.here_home && d.there_home ? ` ${join(d.here_home, hereWin)} here is ${join(d.there_home, farWin)} on ${name}.` : "";
    const radio = (val, text, hint) => h("div", {}, h("label", { class: "check" }, h("input", { type: "radio", name: "paths", checked: val === "same" ? v === "same" : v !== "same",
      onchange: () => change([val === "same" ? "--same" : "--home"]) }), text), h("div", { class: "dim small check-note", text: hint }));
    const here = h("input", { type: "text", placeholder: ON_WINDOWS() ? "a folder here, e.g. D:\\work" : "a folder here, e.g. /data/work", style: "flex:1;min-width:160px" });
    const far = h("input", { type: "text", placeholder: `the folder on ${name}`, style: "flex:1;min-width:160px" });
    b.append(h("div", { class: "stack" },
      h("p", { text: `A project here goes to the matching folder on ${name}, and comes back to the same folder here. Projects already there keep the folder they went to.` }),
      radio("home", "The same place in the home folder", `Any user name, any system.${ex}`),
      radio("same", "The same paths", "Only when both machines have the same folders: the same user name on two Macs, say."),
      h("h3", { text: "Folders that go somewhere else" }),
      pairs.length ? h("div", { class: "pairs" }, pairs.map((x) => h("div", { class: "row" }, h("span", { class: "mono grow", text: `${x[0]}  →  ${x[1]}` }),
        h("button", { class: "small", text: "Remove", onclick: () => change(["--remove", x[0]]) }))))
        : h("p", { class: "dim small", text: "None: every project is in the home folder." }),
      h("div", { class: "row" }, here, h("span", { text: "→" }), far,
        h("button", { class: "small", text: "Add", onclick: () => { if (here.value.trim() && far.value.trim()) change(["--add", here.value.trim(), far.value.trim()]); } })),
      h("p", { class: "dim small", text: "These are tried first, the longest first; a project outside all of them and the home folder cannot go there." }),
      said ? h("p", { class: "warn small", style: "white-space:pre-wrap", text: said }) : null,
      d.warning ? h("p", { class: "warn small", text: "⚠ " + d.warning }) : null, sayLines(d)));
  };
  paint();
  load();
}

// Look back: loose ends, report; tidy up
async function openLooseEnds() {
  const s = sheet("Loose ends", "Loose ends", 860);
  const box = h("div", {}, h("p", { class: "dim" }, h("span", { class: "spin" }), "Looking back over 30 days…"));
  s.body.append(box);
  s.foot.append(h("span", { class: "spacer" }), h("button", { text: "Close", class: "primary", onclick: closeSheet }));
  const d = await J("loose-ends", "--json");
  clear(box);
  const rows = d.loose_ends || [];
  if (!rows.length) box.append(h("p", { class: "okc", text: "Nothing left open in the last 30 days." }));
  for (const r of rows) {
    box.append(h("div", { class: "box", style: "margin-bottom:8px" },
      h("div", { class: "row" }, h("strong", { text: base(r.project) }), h("span", { class: "dim small", text: `${AGENTS[r.agent] || r.agent} · ${ago(r.last)}` }),
        h("span", { class: "grow" }), r.open ? h("span", { class: "okc small", text: "open now" })
          : h("button", { class: "small", text: "Continue", onclick: () => resume([r.project, "--session", r.session, "--agent", r.agent]) })),
      h("ul", {}, (r.items || []).map((it) => h("li", { text: it.text })))));
  }
}
async function openReport(period = "week", by = "project") {
  const args = ["report", "--json", "--by", by];
  if (period === "week" || period === "month") args.push("--since", period);
  const d = await J(...args);
  const s = sheet("Report", "Reports and an AI-use statement", 760);
  const pick = (cur, opts, fn) => h("select", { onchange: (e) => fn(e.target.value) }, opts.map(([v, l]) => h("option", { value: v, text: l, selected: v === cur })));
  s.head.append(h("span", { class: "grow" }), pick(period, [["week", "This week"], ["month", "This month"], ["all", "Everything"]], (v) => openReport(v, by)),
    pick(by, [["project", "By project"], ["area", "By area"], ["agent", "By agent"]], (v) => openReport(period, v)));
  const t = h("table", { class: "list" }, h("thead", {}, h("tr", {}, h("th", { text: by === "project" ? "Project" : by === "area" ? "Area" : "Agent" }),
    h("th", { text: "Hours" }), h("th", { text: "Sessions" }), h("th", { text: "Agents" }))),
  h("tbody", {}, (d.rows || []).map((r) => h("tr", {}, h("td", { text: by === "project" ? base(r.key) : (AGENTS[r.key] || r.key) }),
    h("td", { text: (r.hours || 0).toFixed(1) }), h("td", { text: r.sessions }),
    h("td", { class: "dim small", text: Object.entries(r.agents || {}).map(([a, n]) => `${AGENTS[a] || a} ${n}`).join(", ") })))));
  s.body.append(t);
  s.foot.append(h("span", { class: "dim", text: `${d.total_sessions || 0} sessions · about ${(d.total_hours || 0).toFixed(1)} h of session time` }),
    h("span", { class: "spacer" }), h("button", { text: "Close", class: "primary", onclick: closeSheet }));
}
async function openTidy() {
  const s = sheet("Tidy up", "Tidy up", 860);
  const box = h("div", {}, h("p", { class: "dim" }, h("span", { class: "spin" }), "Looking…"));
  s.body.append(box);
  s.foot.append(h("span", { class: "spacer" }), h("button", { text: "Close", class: "primary", onclick: () => { closeSheet(); refresh(); } }));
  const d = await J("tidy", "--json");
  clear(box);
  const item = (kind, key, path, detail, cands) => {
    const connect = async (dst) => {
      dst = dst || (await pickFolder(`Where is “${base(path)}” now?`));
      if (!dst) return;
      const r = await busy("reconnecting…", () => run(kind === "missing"
        ? ["tidy", "--relink=" + key, "--to=" + dst, "--apply", "--json"] : ["bind", "--store=" + key, "--to=" + dst, "--apply"]));
      if (!r.ok) await tell("That did not work", r.out + r.err);
      openTidy();
    };
    box.append(h("div", { class: "box", style: "margin-bottom:8px" },
      h("div", { class: "row" }, h("strong", { text: base(path) }), h("span", { class: "dim small", text: detail }), h("span", { class: "grow" }),
        h("button", { class: "small", text: "Choose Its Folder…", onclick: () => connect() }),
        kind === "missing" ? h("button", { class: "small", text: "Forget…", onclick: async () => {
          if (!(await confirmIt(`Forget “${base(path)}”?`, "aht stops tracking this folder. Its agent history is kept, and a backup can bring it back to any folder later.", "Forget"))) return;
          await run(["forget", "--uuid", key, "--apply"]); openTidy();
        } }) : null),
      h("div", { class: "dim small mono", text: tilde(path) }),
      (cands || []).slice(0, 3).map((c) => h("div", { class: "row small" }, "Maybe now at", h("span", { class: "mono", text: tilde(c.path) }),
        h("span", { class: "dim", text: (c.reasons || []).join(", ") }), h("button", { class: "small", text: "That's It", onclick: () => connect(c.path) })))));
  };
  for (const m of d.missing || []) item("missing", m.uuid, m.path, (m.agents || []).length ? "history of " + m.agents.map((a) => AGENTS[a] || a).join(", ") : "no history", m.candidates);
  for (const o of d.orphans || []) item("orphan", o.store, o.was || o.store, "Claude Code history without its folder", o.candidates);
  if (!(d.missing || []).length && !(d.orphans || []).length) box.append(h("p", { class: "okc", text: "Nothing to tidy up." }));
}

/** A folder from the system's chooser; "" after Cancel. Only where no
 * chooser could be shown (Linux without zenity, say) is the path asked for as text. */
async function pickFolder(prompt) {
  const r = await busy("waiting for a folder…", () => post("/api/pick-folder", { prompt }));
  if (r.path) return r.path;
  if (LOST) return "";
  if (r.chooser === false) {
    const typed = window.prompt(prompt + "\n\nType or paste the folder's full path:");
    return typed ? typed.trim() : "";
  }
  if (typeof r.not_folder === "string") {
    const x = r.not_folder.trim().replace(/^"(.*)"$/, "$1");
    await tell("That is not a folder", /^([a-z]:|[\\/~])/i.test(x) ? `There is no folder at “${x}”.`
      : `${x ? `“${x}” is` : "That is"} not a folder on a disk. Choose a folder, or type its full path.`);
  }
  return "";
}

// ---- Sessions ---------------------------------------------------------------------

async function loadBoard() {
  S.boardLoading = true; draw();
  const d = await J("board", "--json");
  S.board = d.machines || [];
  S.boardAt = Date.now(); S.boardLoading = false;
  if (S.tab === "sessions" || S.tab === "machines") draw();
}
function drawSessions(m) {
  if (!S.board && !S.boardLoading) loadBoard();
  const head = h("div", { class: "row" }, h("span", { class: "dim", text: "Agent sessions that are open now, here and on your other machines." }),
    h("span", { class: "grow" }), S.boardLoading ? h("span", { class: "spin" }) : null,
    S.boardAt ? h("span", { class: "dim small", text: "updated " + ago(S.boardAt / 1000) }) : null,
    h("button", { text: "Refresh", disabled: S.boardLoading, onclick: loadBoard }), helpBtn("Sessions: what runs right now"));
  m.append(head);
  for (const b of S.board || []) {
    // a machine that does not answer keeps the sessions it had when it last
    // did (last_sessions), greyed: "as of 11:40"
    const old = !b.reachable || b.stale;
    const rows = old ? b.last_sessions || [] : b.sessions || [];
    const g = h("div", { class: "group", style: "margin-top:12px" }, h("div", { class: "title" }, h("span", { text: b.machine + (b.local ? " (this computer)" : "") }),
      old ? h("span", { class: "warn small", text: (b.last_heard ? `has not answered since ${clock(b.last_heard)}` : "did not answer") + (b.error ? ": " + b.error : "") }) : null));
    const list = h("div", { class: "box" + (old ? " stale" : "") });
    if (!old && !rows.length) list.append(h("p", { class: "dim", text: "No agent session open." }));
    if (old && rows.length) list.append(h("div", { class: "dim small", text: b.last_heard ? `as of ${clock(b.last_heard)}` : "as last heard" }));
    for (const s of rows) {
      // a window aht runs another agent in there: its status from the
      // window's output ("working", "quiet for 6 min", "exited")
      const ws = windowStatus(s);
      const cls = old ? "" : ws ? ws.cls : s.raw_status === "waiting" ? "waiting" : s.raw_status === "busy" ? "working" : "";
      list.append(h("div", { class: "row" + (ws ? " in-window" : ""), style: "padding:5px 0;border-bottom:1px solid var(--line)" },
        h("strong", { text: base(s.project) }), h("span", { class: "badge " + cls, text: ws ? ws.text : s.status || s.raw_status || "" }),
        ws && ws.hint ? h("span", { class: "dim small hint", text: ws.hint }) : null,
        s.waiting_for ? h("span", { class: "warn small", text: s.waiting_for }) : null,
        h("span", { class: "dim small", text: [AGENTS[s.agent] || s.agent, s.title || s.name, s.since ? ago(s.since) : ""].filter(Boolean).join(" · ") }),
        h("span", { class: "grow" }),
        (s.issues || []).length ? h("span", { class: "warn small", text: s.issues.join(", ") }) : null,
        b.local && s.pid && s.agent === "claude" ? h("button", { class: "small", text: "End Process…", onclick: async () => {
          if (!(await confirmIt("End this session's process?", "Its conversation stays; you can continue it later.", "End It"))) return;
          await run(["checkup", "--close", String(s.pid), "--apply"]); loadBoard();
        } }) : null));
    }
    if (list.childNodes.length) g.append(list);
    m.append(g);
  }
}

// ---- Search -----------------------------------------------------------------------

function drawSearch(m) {
  const q = h("input", { type: "search", placeholder: "Words from any session, in any agent", value: S.query, style: "width:420px" });
  // every machine aht can ask (search --everywhere): asked in parallel, this
  // computer's hits first
  const others = CAN_REACH() && Object.keys((S.status.handover || {}).remotes || {}).length > 0;
  const everywhere = () => others && !!S.everywhere;
  const go = async () => {
    S.query = q.value.trim();
    if (!S.query) return;
    S.searching = true; draw();
    // after --, "-rf" is text to find
    const all = everywhere();
    const a = await run(["search", "--json", ...(all ? ["--everywhere"] : []), "--", S.query]);
    const d = a.json || {};
    S.hits = d.results || [];
    S.searched = all ? d.machines || [] : null;
    S.searchError = a.json ? null : (a.err + a.out).trim() || null;
    S.searching = false; draw();
  };
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  m.append(h("div", { class: "row" }, q, h("button", { class: "primary", text: "Search", onclick: go }),
    others ? h("label", { class: "check" }, h("input", { type: "checkbox", checked: everywhere(),
      onchange: (e) => { S.everywhere = e.target.checked; if (S.hits && q.value.trim()) go(); } }), "Also on my other machines") : null,
    S.searching ? h("span", { class: "spin" }) : null, helpBtn("Search every session")));
  setTimeout(() => q.focus(), 0);
  if (S.searchError && !S.searching) m.append(h("p", { class: "warn", style: "white-space:pre-wrap", text: S.searchError }));
  // the other machines (this one is machine null): a line for each that
  // could not be searched, with why, and one for those that were
  const machines = (S.searched || []).filter((x) => x.machine);
  const failed = (x) => !x.reachable || x.indexed === false || !!x.error;
  for (const x of machines.filter(failed)) {
    const why = String(x.error || "").split("\n")[0];
    m.append(h("p", { class: "warn small", style: "margin:6px 0 0", text: `${x.machine} was not searched: ` + (!x.reachable
      ? "not reachable" + (why ? ` (${why})` : "") : x.indexed === false ? "no search index (aht is not installed there)" : why) }));
  }
  const asked = machines.filter((x) => !failed(x));
  if (asked.length) m.append(h("p", { class: "dim small", style: "margin:6px 0 0", text: "Also searched: " + asked.map((x) =>
    `${x.machine} (${plural(x.results || 0, "result")}${x.index_at ? ", index updated " + ago(x.index_at) : ""})`).join(", ") }));
  if (!S.hits) return;
  if (!S.hits.length && !S.searchError) m.append(h("p", { class: "dim", text: "Nothing found." }));
  const labelled = (S.searched || []).length > 0 || S.hits.some((r) => r.machine);
  for (const r of S.hits) {
    // a hit on another machine: Continue and Restore act here, so it offers
    // Continue Here… (Pick Up from that machine, with that session) instead;
    // not from a PC, which starts every Pick Up itself
    const there = !!r.machine, fromPC = there && isPC(r.machine);
    const box = h("div", { class: "box", style: "margin-top:8px" },
      h("div", { class: "row" }, h("strong", { text: r.title || "(no title)" }),
        labelled ? h("span", { class: "badge" + (there ? " working" : ""), text: there ? r.machine : "this computer" }) : null,
        h("span", { class: "dim small", text: `${base(r.project)} · ${AGENTS[r.agent] || r.agent} · ${when(r.updated)}` }),
        h("span", { class: "grow" }),
        // as the core offers them: only where the project folder is there
        fromPC ? h("span", { class: "dim small pc-hit", text: `Continue it on ${r.machine}`, title: `A Windows PC starts Pick Up and Leave a Note itself: on ${r.machine}, Leave a Note on this computer to go on with it here.` })
          : there ? h("button", { class: "small", text: "Continue Here…", title: `Pick up this session's work from ${r.machine}`, onclick: () => continueFromThere(r) })
          : r.resume ? h("button", { class: "small", text: "Continue", onclick: () => resume([r.project, "--session", r.session, "--agent", r.agent]) })
          : r.restore && r.restore.project ? h("button", { class: "small", text: "Restore…", onclick: async () => {
            if (!(await confirmIt("Bring this session back?", `“${r.title}” was deleted from ${base(r.project)}'s history; a backup still holds it. Restoring adds what is missing and changes nothing that is there.`, "Restore"))) return;
            const x = await busy("restoring…", () => run(["restore", r.restore.project, "--uuid", r.restore.uuid, "--stamp", r.restore.stamp, "--apply"]));
            await tell(x.ok ? "Restored" : "Restoring did not work", x.ok ? "Continue it from the result list." : x.out + x.err);
            if (x.ok) go();
          } }) : null));
    for (const hit of r.hits || []) box.append(h("div", { class: "small" }, h("span", { class: "dim", text: (hit.role === "user" ? "you" : hit.role) + ": " }), inline(hit.snippet || "")));
    m.append(box);
  }
}

// ---- Machines ----------------------------------------------------------------------

function drawMachines(m) {
  const ho = S.status.handover || {};
  if (!CAN_REACH()) {
    // a core that says can_reach: false has no ssh client to ask with
    m.append(h("div", { class: "box" }, h("h2", { text: "Your other machines", style: "margin-top:0" }),
      h("p", { text: ON_WINDOWS() && "can_reach" in ho
        ? "aht asks your other machines over ssh, and this PC has no ssh client. Add Windows' own in Settings → System → Optional features → OpenSSH Client, then open this tab again."
        : "Handing a project over, keeping it in sync and backups on another machine need an ssh client, and aht finds none on this computer." }),
      helpBtn(ON_WINDOWS() ? "A Windows PC with your other machines" : "Hand a project over")));
    return;
  }
  const send = CAN_HAND_OVER();
  const remotes = Object.entries(ho.remotes || {});
  m.append(h("div", { class: "row" }, h("span", { class: "dim", text: send ? "The machines projects can be handed over to."
    : ON_WINDOWS() ? PC_MACHINES : "The machines whose sessions aht shows and searches." }), h("span", { class: "grow" }),
    h("button", { text: "Add a Machine…", onclick: addMachine }), helpBtn(ON_WINDOWS() ? "A Windows PC with your other machines" : "Hand a project over")));
  if (!remotes.length) m.append(h("p", { class: "dim", text: "None yet." }));
  else m.append(h("p", { class: "dim small", style: "margin:6px 0 0", text: "Watch: every 2 minutes aht asks that machine for sessions that wait for you, and tells you." }));
  for (const [name, r] of remotes) {
    const winBox = !answers(r);                      // a PC aht cannot ask (or not yet)
    const box = h("div", { class: "box", style: "margin-top:8px" }, h("div", { class: "row" }, h("strong", { text: name }),
      h("span", { class: "dim mono", text: r.ssh || "" }), r.system ? h("span", { class: "dim small", text: SYSTEMS[r.system] || r.system }) : null,
      send && name === ho.default_remote ? h("span", { class: "badge ok", text: "used for handovers" }) : null,
      h("span", { class: "grow" }),
      // a PC aht cannot ask is never handed a project: it brings one there itself
      send && name !== ho.default_remote && !winBox ? h("button", { class: "small", text: "Use This One", onclick: async () => { await run(["remote", "default", name]); refresh(); } }) : null,
      // a PC brings nothing here from its side: Bring Here starts on the PC
      r.system !== "Windows" ? h("button", { class: "small", text: "Bring a Project Here…", onclick: () => bringList(name) }) : null,
      send && !winBox ? menu("Sync", [["Keep All Projects in Sync…", () => syncAll(name, true)],
        ["Stop Keeping All in Sync…", () => syncAll(name, false), !S.projects.some((p) => p.mirror)]], { right: true, small: true }) : null,
      h("button", { class: "small", text: "Check…", onclick: () => checkMachine(name) }),
      h("button", { class: "small", text: "Remove…", onclick: async () => {
        if (!(await confirmIt(`Remove ${name}?`, "aht forgets this machine. Nothing on it is deleted.", "Remove"))) return;
        // a machine that still holds a project stays: aht says how to release it
        const r = await run(["remote", "remove", name]);
        if (!r.ok) await tell(`${name} is not removed`, (r.err + r.out).trim() || "aht gave no answer.");
        refresh();
      } })),
      h("div", { class: "row" },
        h("label", { class: "check", title: winBox ? pcWhy(r) : null },
          h("input", { type: "checkbox", checked: !!r.watch, disabled: winBox, onchange: (e) => watchMachine(name, e.target) }), "Watch"),
        h("span", { class: "grow" }), heardLine(name, r)),
      // why, in the core's words, and how to set the PC up
      winBox ? h("div", { class: "row pc-why" }, h("span", { class: "warn small grow", text: pcWhy(r) }), helpBtn(PC_SETUP)) : null,
      // a PC that answers starts no session: its tray offers Continue here
      !winBox && r.system === "Windows" && send ? h("div", { class: "dim small pc-note", text: "No session starts on a PC: Hand Over copies a project there, and the PC's tray offers Continue here." }) : null,
      pathsLine(name, r),
      send ? syncLine(name) : null);
    m.append(box);
  }
}
/** The projects kept in sync with a machine; a paused one asks in its
 * project, and Keep All Projects in Sync leaves it paused. */
const syncedWith = (name) => S.projects.filter((p) => p.mirror === name && !p.away);
const pausedWith = (name) => syncedWith(name).filter((p) => syncPaused(p));
function syncLine(name) {
  const all = syncedWith(name), paused = pausedWith(name);
  if (!all.length) return null;
  const go = (p) => { S.tab = "projects"; S.selection = p.real_path; drawTop(); draw(); };
  return h("div", { class: "row small synced" },
    h("span", { class: "dim", text: `${plural(all.length, "project")} kept in sync with ${name}` }),
    paused.length ? h("span", { class: "warn", text: `· ${paused.length} paused:` }) : null,
    paused.map((p) => h("button", { class: "link", text: base(p.real_path), title: tilde(p.real_path), onclick: () => go(p) })));
}
/** Keep All Projects in Sync (or Stop Keeping All in Sync): what the first
 * copy sends, then the question.  A paused project stays paused: it is
 * named, with "2 paused", to be settled in its own project. */
async function syncAll(name, on) {
  const plan = await busy(on ? "adding up what the first copy sends…" : "checking…", () =>
    dryRun(["mirror", "--all", on ? "--on" : "--off", "--to", name, "--json"]));
  const paused = on ? pausedWith(name) : [];
  const stays = paused.length ? `${paused.length} paused: ${paused.map((p) => base(p.real_path)).join(", ")}. `
    + `${paused.length === 1 ? "It stays" : "They stay"} paused until you choose what happens to the work there, in ${paused.length === 1 ? "its project" : "each project"}.` : "";
  const rows = plan.projects || [];
  if (problems(plan) || !rows.length) return tell("Nothing to do", [sentence(problems(plan) || "every project is in sync already").trim(), stays].filter(Boolean).join("\n\n"));
  const every = Number(S.config.mirror_interval_minutes) || 30;
  const top = rows.slice(0, 6).map((r) => "• " + base(r.project) + (on ? ` — ${bytes(r.bytes)}` : "")).join("\n");
  // folders here that are copies of another machine's projects (`copies_skipped`: their paths)
  const copies = plan.copies_skipped || [];
  const left = copies.length ? `\n\nLeft out: ${plural(copies.length, "folder")} that ${copies.length === 1 ? "is a copy" : "are copies"} of another machine's projects (${copies.map(base).join(", ")}).` : "";
  const body = on
    ? `${plural(rows.length, "project")} get a copy on ${name}, about ${(Number(plan.bytes || 0) / 1e9).toFixed(1)} GB the first time (it runs in the background and can take a while); after that only changes travel, every ${every} minutes. The biggest:\n\n${top}`
      + "\n\nProjects inside another project travel with it. Rebuilt folders such as node_modules stay behind." + left + (stays ? "\n\n" + stays : "")
    : `${plural(rows.length, "project")} stop being kept in sync. The copies on the other machine stay where they are.`;
  if (!(await confirmIt(on ? `Keep every project in sync with ${name}?` : "Stop keeping every project in sync?", body, on ? "Keep All in Sync" : "Stop"))) return;
  const r = await busy(on ? "switching it on…" : "switching it off…", () => run(["mirror", "--all", on ? "--on" : "--off", "--to", name, "--apply", "--json"]));
  const d = r.json || {};
  if (!d.applied) await tell(on ? "Not kept in sync" : "Not stopped", problems(d) || (r.err + r.out).trim() || "aht gave no answer.");
  else toast(on ? `${plural(rows.length, "project")} kept in sync with ${name}; the first copies run in the background.` : `${plural(rows.length, "project")} no longer kept in sync.`);
  refresh();
}
/** When aht last heard from a machine (`last_heard`: when it last answered
 * the session board, which the notices ask every 2 minutes for a watched
 * one; nothing is asked to show it).  A watched machine silent for 10
 * minutes, or one that did not answer the board this window asked, has not
 * answered since then. */
function heardLine(name, r) {
  const b = (S.board || []).find((x) => !x.local && x.machine === name);
  const heard = Math.max(Number(r.last_heard) || 0, Number(b && b.last_heard) || 0) || null;
  const failed = b && !b.reachable && !(heard && heard * 1000 > S.boardAt);
  if (failed || (r.watch && heard && Date.now() / 1000 - heard >= 600)) {
    return h("span", { class: "warn small", text: heard ? `has not answered since ${clock(heard)}` : "has not answered" });
  }
  return h("span", { class: "dim small", text: heard ? "last heard " + ago(heard) : "not heard from yet" });
}
/** The Watch switch: `remote watch NAME [--off]`. */
async function watchMachine(name, box) {
  const on = box.checked;
  const a = await run(["remote", "watch", name, ...(on ? [] : ["--off"]), "--json"]);
  const d = a.json || {};
  if (!a.ok || !d.applied) {
    box.checked = !on;
    await tell(on ? `${name} is not watched` : `${name} is still watched`, problems(d) || (a.err + a.out).trim() || "aht gave no answer.");
  } else toast(on ? `Watching ${name}: a session there that waits for you gives a notice.` : `${name} is no longer watched.`);
  refresh();
}
/** What a fix says, with each `command` in it to copy; a fix that is only a
 * command ("sudo apt install -y tmux", "here:  brew install rsync") copies
 * whole; one that is a sentence ("Turn on Remote Login …") is only said. */
function fixLine(fix) {
  const copy = (t) => h("button", { class: "small", text: "Copy", title: t, onclick: () => navigator.clipboard.writeText(t).then(() => toast("Copied.")) });
  const line = h("div", { class: "small fix" });
  const parts = String(fix).split(/(`[^`]+`)/);
  if (parts.length > 1) {
    for (const x of parts) {
      if (/^`[^`]+`$/.test(x)) line.append(h("code", { text: x.slice(1, -1) }), " ", copy(x.slice(1, -1)));
      else if (x) line.append(x);
    }
  } else if (/\.$/.test(fix) || /^[A-Z]/.test(fix) || /^(nothing to do|open )/i.test(fix)) {
    line.append(fix);
  } else {
    line.append(h("span", { class: "mono", text: fix }), " ", copy(String(fix).replace(/^[^:]*:\s{2,}/, "")));
  }
  return line;
}
/** Check: what this machine has and lacks, for asking it (its sessions,
 * search, Watch) and for handing a project over to it; each missing piece
 * with what fixes it. */
async function checkMachine(name) {
  const send = CAN_HAND_OVER();
  const s = sheet(`Check ${name}`, "Hand a project over", 720);
  const box = h("div", {}, h("p", { class: "dim" }, h("span", { class: "spin" }), `Asking ${name}…`));
  s.body.append(box);
  s.foot.append(h("button", { text: "Check Again", onclick: () => checkMachine(name) }), h("span", { class: "spacer" }),
    h("button", { text: "Close", class: "primary", onclick: closeSheet }));
  const a = await run(["remote", "check", name, "--json"]);
  if (!$("#sheet").contains(box)) return;            // closed meanwhile
  clear(box);
  const d = a.json || {};
  const r = (d.machines || []).find((x) => x.remote === name) || (d.machines || [])[0];
  // a PC: how to set it up when it does not answer; the Machines tab then
  // shows what the core learnt
  const pc = (r && r.system || (remoteRow(name) || {}).system) === "Windows";
  if (pc) refresh();
  if (!r) return box.append(h("p", { class: "warn", style: "white-space:pre-wrap", text: problems(d) || (a.err + a.out).trim() || `${name} did not answer.` }), pc ? pcSetup() : null);
  noteMovers(d);
  const rows = r.checks || [];
  // `transfer`: what copies files to and from it, unless a row says so already
  const mover = MOVER[r.transfer] && !rows.some((c) => c.key === "transfer" || /^copies files/i.test(c.check || ""))
    ? h("p", { class: "small" }, "Copies files with ", h("strong", { text: MOVER[r.transfer] }), "."
      + (send ? " Settings → Handover chooses which." : "")) : null;
  const lacks = (g) => rows.filter((c) => c.group === g && c.needed !== false && !c.ok).length;
  const steps = (list) => h("div", { class: "steps" }, list.map((c) => h("div", { class: "step" },
    h("span", { class: "mark " + (c.ok ? "okc" : c.needed === false ? "dim" : "warn"), text: c.ok ? "✓" : c.needed === false ? "·" : "✗" }),
    h("div", { class: "grow" }, h("div", {}, h("strong", { text: c.check || c.name }), c.detail ? h("span", { class: "dim", text: " — " + c.detail }) : null),
      c.fix && !c.ok ? fixLine(c.fix) : null))));
  // a PC that does not answer (`answers` false, its reason in `answers_why`)
  const why = pc && r.answers === false ? r.answers_why || r.error || null : null;
  const noStart = pc && !lacks("ask") && !why && !(r.error && !rows.length) && !rows.some((c) => /^no session starts/i.test(c.check || ""))
    ? " No session starts on a PC: its tray offers Continue here." : "";
  if (r.error && !rows.length) {
    box.append(h("div", { class: "callout" }, h("strong", { text: `aht could not ask ${name}` }),
      h("div", { class: "small", style: "white-space:pre-wrap" }, inline(r.error))));
  } else if (rows.some((c) => c.group)) {
    box.append(h("p", { class: lacks("ask") || why || (send && lacks("handover")) ? "warn" : "okc", text: lacks("ask") || why ? `aht cannot ask ${name} yet: ${why ? pcWhy({ answers_why: why }) : "it needs what is marked ✗ under For asking."}`
      : !send ? `aht can ask ${name}: its sessions, Search and Watch work from here.` + noStart
      : lacks("handover") ? `aht can ask ${name}; handing a project over to it needs what is marked ✗.` + noStart : `${name} is ready: aht can ask it and hand projects over to it.` + noStart }));
  }
  if (pc && (why || lacks("ask") || (r.error && !rows.length))) box.append(pcSetup());
  if (mover) box.append(mover);
  if (rows.some((c) => c.group)) {
    const ask = rows.filter((c) => c.group === "ask"), hand = rows.filter((c) => c.group !== "ask");
    if (ask.length) box.append(h("h3", { text: "For asking" }), h("div", { class: "dim small", text: "What aht needs to see the sessions there, search them and watch the machine." }), steps(ask));
    // where projects cannot be sent from (Windows), what a handover needs is
    // for later: folded away
    if (hand.length && send) box.append(h("h3", { text: "For handing over" }), h("div", { class: "dim small", text: "What handing a project over to it needs." }), steps(hand));
    else if (hand.length) {
      box.append(h("details", { class: "later" }, h("summary", {}, h("h3", { text: "For handing over" })),
        h("div", { class: "dim small", text: "This copy of aht cannot hand projects over; this is what it would need." }), steps(hand)));
    }
  } else if (rows.length) box.append(steps(rows));
}
async function addMachine() {
  const s = sheet("Add a machine", "Hand a project over", 560);
  const name = h("input", { type: "text", placeholder: "a short name, e.g. homebox" });
  const ssh = h("input", { type: "text", placeholder: "user@host, as ssh reaches it" });
  const said = h("div");
  s.body.append(h("div", { class: "stack" }, h("label", {}, "Name ", name), h("label", {}, "Address ", ssh)), said);
  const add = h("button", { class: "primary", text: "Add", onclick: async () => {
    const n = name.value.trim(), t = ssh.value.trim();
    if (!n || !t) return clear(said).append(h("p", { class: "warn small", text: "Give the machine a name and the address ssh reaches it at." }));
    add.disabled = true;
    clear(said).append(h("p", { class: "dim small" }, h("span", { class: "spin" }), `Asking ${t}…`));
    const r = await busy("adding it…", () => run(["remote", "add", n, t]));
    add.disabled = false;
    if (!$("#sheet").contains(said)) return;
    if (!r.ok) {
      const why = (r.err + r.out).trim().replace(/^✗\s*/, "");
      // a PC that does not answer: how to set it up
      return clear(said).append(h("div", { class: "callout" }, h("strong", { text: "Not added" }),
        h("div", { class: "small", style: "white-space:pre-wrap" }, inline(why || "aht gave no answer.")),
        /\bWindows\b|\bPC\b/.test(why) ? pcSetup() : null));
    }
    closeSheet();
    await refresh();
    checkMachine(n);                                // what it lacks, right away
  } });
  s.foot.append(h("span", { class: "spacer" }), h("button", { text: "Cancel", onclick: closeSheet }), add);
}

// ---- Settings ----------------------------------------------------------------------

function group(title, topic, ...kids) {
  return h("div", { class: "group" }, h("div", { class: "title" }, title, topic ? helpBtn(topic) : null), h("div", { class: "box stack" }, kids));
}
function check(label, key, def = true, hint) {
  return h("label", { class: "check" }, h("input", { type: "checkbox", checked: flag(key, def),
    onchange: (e) => setConfig(key, e.target.checked) }), label, hint ? h("span", { class: "dim small", text: hint }) : null);
}
/** Whether a session's start copies the folder (Undo a whole session), as
 * the core has it (`status --json` → effective.checkpoint_on_start).  An
 * older core: the setting when it is set, else on on macOS only, where the
 * copy is a clone that takes no room; on Windows and Linux it is a real
 * copy, so it is off until you turn it on. */
function checkpointsOn() {
  const e = (S.status.effective || {}).checkpoint_on_start;
  if (typeof e === "boolean") return e;
  return "checkpoints" in S.explicit ? !!S.explicit.checkpoints : ON_MAC();
}
function setCheckpoints(on) {
  if (typeof (S.status.effective || {}).checkpoint_on_start === "boolean") S.status.effective.checkpoint_on_start = on;
  S.explicit.checkpoints = on;
  setConfig("checkpoints", on);
}
function choice(label, key, options) {
  return h("div", { class: "row" }, h("span", { style: "width:190px", text: label }),
    h("select", { onchange: (e) => setConfig(key, e.target.value) }, options.map(([v, l]) => h("option", { value: v, text: l, selected: S.config[key] === v }))));
}

function drawSettings(m) {
  const st = S.status;
  const steps = st.getting_started || [];
  const left = steps.filter((x) => !x.ok && !x.optional).map((x) => x.title);
  const more = steps.filter((x) => !x.ok && x.optional).length;
  m.append(h("div", { class: "row dim", style: "margin-bottom:10px" }, "Every setting, also those without a switch here, is in the guide:", helpBtn("All settings")));
  if (steps.length) {
    m.append(group("Getting started", "Getting started", h("div", { class: "row" },
      h("span", { class: left.length ? "warn" : "dim", text: (left.length ? "To do: " + left.join(", ") + "." : "The main steps are done.") + (more ? ` ${plural(more, "optional step")} left.` : "") }),
      h("span", { class: "grow" }), h("button", { text: "Show the Steps…", onclick: showGettingStarted }))));
  }
  const roots = st.watch_roots || [];
  m.append(group("Watched folders", "Setting up",
    roots.map((r) => h("div", { class: "row" }, h("span", { class: "mono grow", text: tilde(r) }),
      h("button", { class: "small", text: "Remove", disabled: roots.length < 2, onclick: () => setConfig("watch_roots", roots.filter((x) => x !== r), true) }))),
    h("div", { class: "row" }, h("button", { text: "Add Folder…", onclick: async () => {
      const p = await pickFolder("Watch this folder: aht notices moves, copies and new projects inside it");
      if (p && !roots.includes(p)) setConfig("watch_roots", roots.concat([p]), true);
    } })),
    h("div", { class: "dim small", text: "aht notices moves, copies and new projects inside these folders. A project elsewhere keeps its history, but aht does not follow it when it moves." })));
  m.append(group("When folders change", "Folders that move",
    choice("A folder moves", "move_policy", [["ask", "Ask me"], ["apply", "Relink automatically"], ["decline", "Never relink (remember the no)"], ["ignore", "Do nothing"]]),
    choice("A folder is copied", "copy_policy", [["ask", "Ask me"], ["duplicate", "Duplicate the history"], ["independent", "Fresh identity, no history"], ["ignore", "Do nothing"]])));
  m.append(group("Histories", "Backups", h("div", { class: "row" }, check("Notifications", "notifications"), check("Back up histories automatically", "backup_enabled"),
    h("span", { class: "grow" }), h("button", { text: "Check All for Secrets…", onclick: () => openSecrets(null) }),
    h("button", { text: "Back Up Now", onclick: async () => {
      const d = await busy("backing up the histories…", () => J("backup", "--json"));
      const c = Object.entries(d.counts || {});
      toast(c.length ? "Backed up: " + c.map(([k, v]) => `${v} ${k}`).join(", ") : "Nothing to back up.");
    } }))));
  const phone = h("input", { type: "text", value: S.config.notify_phone || "", placeholder: "ntfy:my-topic", style: "width:240px" });
  m.append(group("Notices", "Know when a session needs you",
    h("div", { class: "row" }, check("When a session waits for you", "notify_waiting"), check("When a long piece of work is done", "notify_finished")),
    h("div", { class: "row" }, "Also send them to my phone:", phone, h("button", { text: "Save", onclick: () => setConfig("notify_phone", phone.value.trim()) }),
      h("button", { text: "Send a Test", onclick: async () => { const r = await run(["notices", "--test"]); toast(r.out.trim() || "Sent."); } })),
    h("div", { class: "dim small", text: "ntfy: a topic you follow in the free ntfy app. Anyone who knows an ntfy.sh topic's name can read it, so choose a name that is hard to guess." })));
  m.append(group("Safety nets (no tokens)", "Undo a whole session",
    h("label", { class: "check checkpoints" }, h("input", { type: "checkbox", checked: checkpointsOn(), onchange: (e) => setCheckpoints(e.target.checked) }),
      "Copy the folder when a session starts, to undo a whole session",
      h("span", { class: "dim small", text: "On Windows and Linux it makes a real copy of the folder, which takes room." })),
    check("Tell me when Claude stops at its usage limit", "notify_limit")));
  const tok = (label, key, cost) => h("div", { class: "row" }, h("label", { class: "check" }, h("input", { type: "checkbox", checked: flag(key, false),
    onchange: async (e) => { if (e.target.checked && !(await tokensOK(key, label.toLowerCase()))) e.target.checked = false; else if (!e.target.checked) setConfig(key, false); } }), label),
    cost ? h("span", { class: "dim small", text: cost }) : null);
  m.append(group("Uses tokens — off until you turn it on", "What uses tokens",
    tok("A new Claude session learns where the last one in its folder stopped", "informed_sessions", "a few hundred tokens per new session"),
    h("div", { class: "row" }, tok("When Claude stops at its limit, offer to go on in", "limit_switch", null),
      h("select", { onchange: (e) => setConfig("limit_switch_to", e.target.value) }, ["kimi", "codex", "agy", "vibe"].filter((a) => !["agy", "vibe"].includes(a) || (S.status.agent_clis || {})[a])
        .map((v) => h("option", { value: v, text: AGENTS[v], selected: S.config.limit_switch_to === v })))),
    tok("Second opinion: one task, two agents, compared", "second_opinion", "both agents work"),
    CAN_HAND_OVER() ? tok("Night shift: hand a project over with a task, on a timer", "night_shift", "the agent works while you are away") : null,
    h("div", { class: "dim small", text: "Each of these makes an agent read or work, which counts against your plan or API bill. aht's own work — watching, search, backups, reports, loose ends — never uses tokens." })));
  m.append(permissionsGroup());
  // a PC too, while it answers (aht's own copy moves the backups there); one
  // that does not is left out, unless it is the one chosen now
  if (CAN_HAND_OVER() || CAN_REACH()) {
    const off = S.config.offsite_backup || "";
    const rs = (st.handover || {}).remotes || {};
    const names = Object.keys(rs).filter((n) => answers(rs[n]) || n === off).sort();
    if (off && !names.includes(off)) names.push(off);
    const mute = off && rs[off] && !answers(rs[off]) ? rs[off] : null;
    m.append(group("Backups on another machine", "Backups",
      h("div", { class: "row" }, "Keep a copy of the history backups on",
        h("select", { onchange: (e) => setConfig("offsite_backup", e.target.value) },
          [["", "no other machine"]].concat(names.map((n) => [n, rs[n] && !answers(rs[n]) ? `${n} (aht cannot ask it)` : n]))
            .map(([v, l]) => h("option", { value: v, text: l, selected: off === v }))),
        h("span", { class: "grow" }),
        h("button", { text: "Copy Now", disabled: !off, onclick: copyBackupsNow }),
        h("button", { text: "Fetch Backups From…", disabled: !off || !CAN_REACH(), onclick: () => fetchBackups(off) })),
      mute ? h("div", { class: "row pc-why" }, h("span", { class: "warn small grow", text: pcWhy(mute) }), helpBtn(PC_SETUP)) : null,
      h("div", { class: "dim small", text: names.length
        ? "After each daily backup, aht adds the new ones to a folder of this computer's own there. A backup there goes only after aht removed it here, and at least 3 per project stay. Fetch Backups From… brings back the backups any of your computers left there: it adds what is missing here and replaces nothing."
        : "Add one of your other machines in the Machines tab first." })));
  }
  m.append(group("Folder badges", "Folder badges", h("div", { class: "row" }, check("Badge folders", "icons_enabled"), check("Agent symbols", "icons_agent"), check("Git “+”", "icons_git"),
    h("span", { class: "grow" }), h("button", { text: "Refresh All", onclick: () => busy("refreshing the badges…", () => run(["icons", "--refresh"])) }),
    h("button", { text: "Clear All…", onclick: async () => {
      if (!(await confirmIt("Clear every badge?", "aht takes its badges off every folder; Refresh All puts them back.", "Clear"))) return;
      const agent = flag("icons_agent"), git = flag("icons_git");
      await busy("clearing the folder badges…", async () => {
        await run(["config", "--set", "icons_enabled=true", "icons_agent=false", "icons_git=false", "--no-reload"]);
        await run(["icons", "--refresh"]);
        await run(["config", "--set", `icons_agent=${agent}`, `icons_git=${git}`, "--no-reload"]);
      });
    } }))));
  if (CAN_HAND_OVER()) {
    // the select keeps the focus, so refresh() draws nothing: the line below follows it here
    const movers = h("div", { class: "dim small", id: "movers", text: moversLine() });
    const machines = Object.keys((st.handover || {}).remotes || {}).length;
    m.append(group("Handover", "Hand a project over",
      check("Reachable from the Claude app (Remote Control)", "handover_remote_control"), check("Compress what is sent", "handover_compress"),
      check("Use mosh to open a session when it gets through", "handover_mosh"), check("A folder trusted here is trusted on the other machine", "handover_carry_trust"),
      h("div", { class: "row" }, h("span", { text: "Copies files with" }),
        h("select", { id: "transfer", onchange: (e) => { setConfig("handover_transfer", e.target.value); movers.textContent = moversLine(); } },
          Object.entries(TRANSFER).map(([v, l]) => h("option", { value: v, text: l, selected: transferMode() === v }))),
        h("span", { class: "grow" }),
        machines && CAN_REACH() ? h("button", { class: "small", text: "Ask the Machines", title: "Ask each machine whether it has rsync", onclick: async () => {
          const a = await busy("asking the machines…", () => run(["remote", "check", "all", "--json"]));
          noteMovers(a.json);
          movers.textContent = moversLine();
        } }) : null),
      machines ? movers : null,
      h("div", { class: "dim small", text: "rsync sends only the changed parts of a big file. aht's own copy needs nothing installed and also copies to and from Windows." })));
  }
  const be = h("div", { class: "stack" });
  for (const b of st.backends || []) {
    be.append(h("div", { class: "row small" }, h("span", { class: b.available ? "okc" : "dim", text: b.available ? "✓" : "·", style: "width:14px" }),
      h("span", { style: "width:90px", text: b.name }), h("span", { class: "dim mono grow ellipsis", text: tilde(b.root) }),
      b.root_source !== "default" ? h("span", { class: "dim", text: b.root_source }) : null,
      h("button", { class: "small", text: "Choose…", onclick: async () => {
        const p = await pickFolder(`Where does ${b.label} keep its history?`);
        if (p) { await run(["backends", "--set-root", `${b.name}=${p}`]); refresh(); }
      } })));
  }
  be.append(h("div", { class: "row" }, h("span", { class: "grow" }), h("button", { text: "Reset All to Defaults", onclick: async () => {
    if (!(await confirmIt("Reset every agent CLI location to its default?", "Only the store paths aht looks at are reset — no history is touched.", "Reset"))) return;
    await run(["backends", "--clear-root", ...(st.backends || []).map((b) => b.name)]); refresh();
  } })));
  m.append(group("Where each agent keeps its history", "All settings", be));
  const login = (st.autostart || {});
  m.append(group("This computer", "Settings",
    login.supported ? h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!login.on, disabled: !login.on && !loginWorks(), onchange: async (e) => {
      await run(["autostart", e.target.checked ? "on" : "off"]); refresh(); } }), "Start aht's tray at login") : null,
    login.supported && login.runs === false ? h("div", { class: "dim small", text: "aht's tray cannot run on this computer yet; Getting started says what it needs." }) : null,
    h("div", { class: "row" }, check("Tell me when a new version of aht is out", "update_check", false),
      h("button", { class: "small", text: "Check Now", onclick: checkUpdateNow }), helpBtn("New versions")),
    h("div", { class: "dim small", text: "Once a day aht asks GitHub which version is the latest. GitHub sees your computer's address and which version of aht you run; nothing else is sent. Off until you turn it on." }),
    h("div", { class: "row" }, h("button", { text: "Run Setup Again…", onclick: () => showWelcome(true) }),
      h("button", { text: "Adopt This Computer's Projects…", onclick: adopt }),
      h("button", { text: "Restart Watcher", onclick: () => busy("restarting the watcher…", () => run(["reload"])) })),
    h("div", { class: "row" }, h("button", { text: "Run Diagnostics", onclick: doctor }),
      h("button", { text: "Open Log", onclick: () => post("/api/reveal", { path: st.log && st.log.path }) }),
      h("button", { text: "Open Data Folder", onclick: () => post("/api/reveal", { path: st.aht_home }) })),
    h("div", { class: "dim small", text: "aht keeps every AI coding agent's per-project history connected to its folder. History is never deleted or overwritten. Data: " + tilde(st.aht_home || "") })));
}
/** Settings ▸ Permissions: the level the next agent starts in
 * (`agent_permissions`), and Codex's never-ask flags
 * (`agent_permission_flags`.codex.never: the built-in full bypass, or
 * never asking inside Codex's sandbox). */
const PERM_CHOICES = [["follow", "Follow the session"], ["ask", "Always: ask mode"], ["edits", "Always: edits mode"],
  ["auto", "Always: auto mode"], ["never", "Always: never-ask mode"], ["max:edits", "At most: edits mode"], ["max:auto", "At most: auto mode"]];
const CODEX_SANDBOXED = ["-a", "never", "-s", "workspace-write"];
/** Codex's never-ask flags as set: "sandbox" (never asks, keeps its
 * sandbox), "full" (the built-in full bypass), or "own" (other flags). */
function codexNever() {
  const f = ((S.config.agent_permission_flags || {}).codex || {}).never;
  if (!Array.isArray(f) || !f.length) return "full";
  return JSON.stringify(f) === JSON.stringify(CODEX_SANDBOXED) ? "sandbox" : "own";
}
function setCodexNever(how) {
  const all = JSON.parse(JSON.stringify(S.config.agent_permission_flags || {}));
  const codex = Object.assign({}, all.codex || {});
  if (how === "sandbox") codex.never = CODEX_SANDBOXED.slice();
  else delete codex.never;                // the built-in: --dangerously-bypass-approvals-and-sandbox
  if (Object.keys(codex).length) all.codex = codex; else delete all.codex;
  return setConfig("agent_permission_flags", all);
}
function permissionsGroup() {
  const now = String(S.config.agent_permissions || "follow");
  const choices = PERM_CHOICES.some(([v]) => v === now) ? PERM_CHOICES : PERM_CHOICES.concat([[now, now]]);
  const cx = codexNever();
  const own = cx === "own" ? ((S.config.agent_permission_flags || {}).codex || {}).never.map(shellWord).join(" ") : null;
  const caution = h("div", { class: "warn small", id: "perm-never", text: "Every agent aht starts or continues then never asks, also after a session that asked." });
  caution.hidden = now !== "never";
  return group("Permissions", "The permission level follows the work",
    h("div", { class: "dim small", text: "The agent that continues the work starts in its own equivalent of the session's permission level; aht never raises it by itself." }),
    h("div", { class: "row" }, h("span", { style: "width:190px", text: "The next agent starts in" }),
      h("select", { id: "agent-permissions", onchange: (e) => { caution.hidden = e.target.value !== "never"; setConfig("agent_permissions", e.target.value); } },
        choices.map(([v, l]) => h("option", { value: v, text: l, selected: v === now })))),
    caution,
    h("div", { class: "row" }, h("span", { style: "width:190px", text: "Codex's never-ask mode" }),
      h("select", { id: "codex-never", onchange: (e) => setCodexNever(e.target.value) },
        [["full", "Full bypass (default)"], ["sandbox", "Never ask, keep Codex's sandbox"]].concat(own ? [["own", `Your own flags: ${own}`]] : [])
          .map(([v, l]) => h("option", { value: v, text: l, selected: v === cx, disabled: v === "own" })))),
    h("div", { class: "dim small" }, "Full bypass: ", h("code", { text: "--dangerously-bypass-approvals-and-sandbox" }),
      ", the closest to Claude Code's skip-permissions. Keeping the sandbox: ", h("code", { text: CODEX_SANDBOXED.join(" ") }),
      ": Codex never asks, but writes only inside the project."));
}
async function copyBackupsNow() {
  const a = await busy("copying the backups…", () => job(["backup", "--offsite", "--json"], "copying the backups"));
  const d = a.json || {};
  if (!a.ok) return tell("The backups were not copied", (a.err + a.out).trim() || "aht gave no answer.");
  toast((d.files ? `Copied ${plural(d.files, "backup")} (${bytes(d.bytes)}) to ${d.machine || "the other machine"}.` : `${d.machine || "The other machine"} has every backup already.`)
    + (d.removed ? ` ${plural(d.removed, "older backup")} there ${d.removed === 1 ? "was" : "were"} removed, as ${d.removed === 1 ? "it was" : "they were"} here.` : "")
    // an older aht's folder there that holds backups this computer lacks: left as it is
    + ((d.legacy || []).length ? ` An older aht's folder there (${d.legacy.join(", ")}) was left as it is; Fetch Backups From… can bring its backups here.` : ""),
    (d.legacy || []).length ? 9000 : 4000);
}
/** Fetch Backups From…: every computer's folder of backups on that machine;
 * a fetch adds what is missing here and replaces nothing. */
async function fetchBackups(machine) {
  const s = sheet(`Backups on ${machine}`, "Backups", 760);
  const box = h("div", {}, h("p", { class: "dim" }, h("span", { class: "spin" }), `Asking ${machine}…`));
  s.body.append(h("p", { class: "dim", text: `Each computer that copies its backups to ${machine} has a folder of its own there. Fetch adds the backups that are missing here; nothing here is replaced.` }), box);
  s.foot.append(h("span", { class: "spacer" }), h("button", { text: "Close", class: "primary", onclick: closeSheet }));
  const a = await run(["backup", "--offsite-list", "--json"]);
  const d = a.json || {};
  if (!$("#sheet").contains(box)) return;            // closed meanwhile
  clear(box);
  if (!Array.isArray(d.folders)) {
    return box.append(h("p", { class: "warn", text: problems(d) || (a.err + a.out).trim() || `${machine} did not answer.` }));
  }
  if (!d.folders.length) box.append(h("p", { class: "dim", text: `There are no backups on ${machine} yet.` }));
  for (const f of d.folders) {
    const who = f.name || f.id;
    const facts = [SYSTEMS[f.system] || f.system, f.updated ? "updated " + ago(f.updated) : null, plural(f.projects || 0, "project"),
      `${plural(f.files || 0, "backup")}, ${bytes(f.bytes)}`];
    box.append(h("div", { class: "row", style: "padding:6px 0;border-bottom:1px solid var(--line)" },
      h("div", { class: "grow" }, h("div", { class: "row" }, h("strong", { text: who }),
        f.mine ? h("span", { class: "badge ok", text: "this computer" }) : null,
        f.legacy ? h("span", { class: "badge", text: "older aht", title: "Copied there by an earlier version of aht" }) : null),
      h("div", { class: "dim small", text: facts.filter(Boolean).join(" · ") })),
      h("button", { class: "small", text: "Fetch", disabled: !f.files, onclick: () => fetchFrom(machine, f) })));
  }
}
async function fetchFrom(machine, f) {
  const who = f.name || f.id;
  const a = await busy(`fetching ${who}'s backups…`, () => job(["backup", "--fetch-offsite", "--from=" + (f.id || f.folder || f.name), "--json"], "fetching the backups"));
  const d = a.json || {};
  // files that could not come are in `problems`, and the run then ends with 1:
  // what did arrive still counts
  const probs = Array.isArray(d.problems) ? d.problems : [];
  const notCame = probs.length ? `\n\n${probs.length === 1 ? "This file" : `These ${probs.length} files`} could not come:\n`
    + probs.slice(0, 10).map((p) => `• ${p.name || "?"} — ${p.error || "no reason given"}`).join("\n")
    + (probs.length > 10 ? `\n… and ${probs.length - 10} more` : "") : "";
  if (!a.ok && !(probs.length && d.files)) {
    return tell("The backups were not fetched", probs.length ? `Nothing came from ${who}'s folder on ${machine}.${notCame}`
      : (a.err + a.out).trim() || "aht gave no answer.");
  }
  // a backup is a .zip with its .meta.json: each counts once
  const renamed = Array.isArray(d.renamed) ? d.renamed.filter((x) => /\.zip$/i.test(x)).length : d.renamed || 0;
  tell(probs.length ? "Some backups were not fetched" : d.files ? "Backups fetched" : "Nothing to fetch", (d.files
    ? `${plural(d.files, "backup")} (${bytes(d.bytes)}) came from ${who}'s folder on ${machine}.`
    : `Every backup in ${who}'s folder on ${machine} is here already.`)
    + (renamed ? ` ${plural(renamed, "backup")} had the name of a different one here, so ${renamed === 1 ? "it was" : "they were"} kept under a new name.` : "")
    + (d.files ? " Search finds the sessions in them, and Restore brings one back." : "") + notCame);
}
async function adopt() {
  const d = await busy("looking for projects…", () => J("adopt", "--json"));
  const n = (d.planned || []).length;
  if (!n) return tell("Nothing to adopt", "Every folder with agent history under the watched folders is tracked already.");
  const forgot = (d.planned || []).filter((a) => a.forgotten).length;
  if (!(await confirmIt(`Track ${plural(n, "folder")}?`, (d.planned || []).slice(0, 12).map((a) => "• " + tilde(a.real) + (a.forgotten ? " (you told aht to forget it)" : "")).join("\n") + (n > 12 ? `\n… and ${n - 12} more` : "")
    + (forgot ? `\n\nYou told aht to forget ${n === 1 ? "it" : forgot === n ? "all of them" : forgot === 1 ? "one of them" : `${forgot} of them`}: adopting takes ${forgot === 1 ? "it" : "them"} on again.` : ""), "Adopt"))) return;
  await busy("adopting…", () => run(["adopt", "--apply", "--json"]));
  refresh();
}
async function doctor() {
  const d = await busy("checking…", () => J("doctor", "--json"));
  tell(d.ok ? "Everything checks out" : "Something needs a look", (d.checks || []).map((c) => `${c.ok ? "✓" : "✗"} ${c.check}${c.detail && !c.ok ? " — " + c.detail : ""}`).join("\n"));
}

// ---- Getting started, new versions, welcome ----------------------------------------------

function showGettingStarted() {
  const s = sheet("Getting started", "Getting started", 700);
  s.body.append(h("p", { class: "dim", text: "aht keeps your histories connected on its own. These steps let it do more; each says what it is for, and any of them can wait." }));
  const box = h("div", { class: "steps" });
  for (const x of S.status.getting_started || []) {
    let action = null;
    if (x.id === "login" && loginWorks()) {
      action = h("input", { type: "checkbox", checked: x.ok, onchange: async (e) => { await run(["autostart", e.target.checked ? "on" : "off"]); await refresh(); showGettingStarted(); } });
    } else if (x.id === "chimes" || x.id === "corner") {
      action = null;
    } else if (x.id === "notifications") {
      action = h("input", { type: "checkbox", checked: x.ok, onchange: async (e) => { await setConfig("notifications", e.target.checked); showGettingStarted(); } });
    } else if (x.id === "update_check") {
      action = h("input", { type: "checkbox", checked: x.ok, onchange: async (e) => { await setConfig("update_check", e.target.checked); showGettingStarted(); } });
    }
    box.append(h("div", { class: "step" },
      h("span", { class: "mark " + (x.ok ? "okc" : x.optional ? "dim" : "warn"), text: x.ok ? "✓" : x.optional ? "○" : "!" }),
      h("div", { class: "grow" }, h("div", {}, h("strong", { text: x.title }), x.optional ? h("span", { class: "dim small", text: "  optional" }) : null),
        h("div", { class: "dim", text: x.text }), x.how ? h("div", { text: x.how }) : null), action));
  }
  s.body.append(box);
  s.foot.append(h("button", { text: "Check Again", onclick: async () => { await refresh(); showGettingStarted(); } }), h("span", { class: "spacer" }),
    h("button", { class: "primary", text: "Done", onclick: closeSheet }));
}

function showUpdate() {
  const u = S.status.update || {};
  const s = sheet(`aht ${u.latest || ""} is out`, "New versions", 760);
  s.body.append(h("p", { class: "dim", text: `You have ${u.current || "?"}. What's new:` }), md(u.notes || ""));
  const how = u.upgrade ? "Upgrade runs this in a terminal window: " + u.upgrade
    : u.installer ? `Upgrade downloads ${u.installer} from GitHub, checks it and runs it; aht starts again when it is done.`
    : u.how === "source" ? "The button opens the download page. To upgrade, run git pull in your copy of aht, then linux/install.sh again."
    : "The button opens the download page.";
  s.foot.append(h("span", { class: "dim small", text: how }),
    h("span", { class: "spacer" }), h("button", { text: "Later", onclick: closeSheet }),
    h("button", { class: "primary", text: u.upgrade || u.installer ? "Upgrade" : "Open the Download Page", onclick: async () => {
      closeSheet();
      if (!u.upgrade && !u.installer) return post("/api/open-url", { url: u.url });
      const r = await run(["update", "--upgrade"]);
      if (!r.ok) tell("The upgrade did not start", ((r.out || "") + (r.err || "")).trim());
    } }));
}
async function checkUpdateNow() {
  const d = await busy("asking GitHub for the latest version…", () => J("update", "--now", "--json"));
  await refresh();
  // after a failed ask, "latest" is only what GitHub said the time before
  if (d.newer) showUpdate();
  else if (d.latest && !d.error) tell(`aht ${d.latest} is the latest`, "You have the newest version.");
  else tell("GitHub did not answer", d.error || "Try again later.");
}

/** The first-time setup: Quick Setup or each step (`aht setup`). */
async function showWelcome(again) {
  const W = { page: "hello", roots: [], projects: [], loading: true };
  const s = sheet("Setting up aht", "Setting up", 720);
  const load = async (first) => {
    W.loading = true; paint();
    const chosen = W.roots.filter((r) => r.chosen).map((r) => r.path);
    const d = await J(...["setup", "--json"].concat(first ? [] : ["--roots", ...chosen]));
    if (first) {
      W.roots = (d.roots || []).filter((r) => r.exists || r.chosen).map((r) => ({ path: r.path, chosen: r.chosen || r.projects > 0, projects: r.projects }));
      const pol = d.policies || {}, sw = d.switches || {}, auto = S.status.autostart || {};
      // the tray at login: on the first time; once asked (the installer asks,
      // so do Settings and the tray), as it is set now
      W.answered = !!auto.answered;
      W.asked = W.answered || !!S.status.setup_done;
      Object.assign(W, { moves: pol.moves || "ask", copies: pol.copies || "ask",
        badges: sw.badges !== false, backups: sw.backups !== false, notifications: sw.notifications !== false,
        update: !!sw.update_check, login: W.asked ? !!auto.on : true });
      W.loginFirst = W.login;         // where the switch started: a change from it is an answer
      if (W.roots.some((r) => r.chosen && !(d.roots || []).find((x) => x.path === r.path && x.chosen))) return load(false);
    } else {
      for (const r of d.roots || []) { const x = W.roots.find((y) => y.path === r.path); if (x) x.projects = r.projects; }
    }
    // a project the user told aht to forget comes back only when ticked again
    W.projects = (d.projects || []).map((p) => ({ path: p.path, agents: p.agents || [], forgotten: !!p.forgotten, chosen: !p.forgotten }));
    W.elsewhere = d.elsewhere || [];
    W.loading = false; paint();
  };
  const names = (ps, most = 4) => ps.map(tilde).slice(0, most).join(", ") + (ps.length > most ? ` and ${ps.length - most} more` : "");
  const btns = (back, next, go, enabled = true) => [back ? h("button", { text: "Back", onclick: () => { W.page = back; paint(); } }) : null,
    h("span", { class: "spacer" }), h("button", { class: "primary", text: next, disabled: !enabled || W.loading, onclick: go })];
  const bullet = (i, t) => h("div", {}, h("span", { class: "i", text: i }), h("span", { text: t }));
  // Quick Setup keeps the rules and switches as they are (aht's defaults the
  // first time), so its page says what they are
  const folderRules = () => {
    if (W.moves === "ask" && W.copies === "ask") return "Ask you before it relinks a folder that moved or was copied.";
    const moved = { ask: "Ask you before it relinks a folder that moved", apply: "Relink a moved folder without asking you",
      decline: "Never relink a moved folder", ignore: "Do nothing when a folder moves" }[W.moves] || "Keep your rule for a folder that moves";
    const copied = { ask: "ask you what to do with a copied folder", duplicate: "give a copied folder a copy of the history",
      independent: "give a copied folder a fresh start, without history", ignore: "do nothing when a folder is copied" }[W.copies] || "keep your rule for a copied folder";
    return moved + "; " + copied + ".";
  };
  const extrasLine = () => W.badges && W.backups ? "Badge project folders, and back up the histories once a day."
    : W.badges ? "Badge project folders." : W.backups ? "Back up the histories once a day." : "";
  const toggle = (label, key) => h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!W[key], onchange: (e) => { W[key] = e.target.checked; } }), label);
  // the tray at login as it will be set, with its box right there: a no given
  // before (in the installer, say) is kept, and says so
  const loginLine = (label) => h("div", {}, h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!W.login,
    onchange: (e) => { W.login = e.target.checked; paint(); } }), label),
    !W.login && W.asked ? h("div", { class: "dim small check-note", text: (W.answered ? "You turned this off when you installed aht, or later."
      : "It is off now.") + " Tick the box to turn it on." }) : null);
  const pol = (label, key, opts) => h("div", { class: "row" }, h("span", { style: "width:200px", text: label }),
    h("select", { onchange: (e) => { W[key] = e.target.value; } }, opts.map(([v, l]) => h("option", { value: v, text: l, selected: W[key] === v }))));
  const apply = async () => {
    W.page = "working"; W.working = "saving your choices…"; paint();
    const on = (b) => (b ? "on" : "off");
    const chosen = W.projects.filter((p) => p.chosen).map((p) => p.path);
    const r = await run(["setup", "--apply", "--json", "--roots", ...W.roots.filter((x) => x.chosen).map((x) => x.path), "--adopt", ...chosen,
      "--moves", W.moves, "--copies", W.copies, "--badges", on(W.badges), "--backups", on(W.backups),
      "--notifications", on(W.notifications), "--update-check", on(W.update)]);
    if (!r.ok) { W.failed = r.out + r.err; paint(); return; }
    // the tray at login when the switch differs from it, or from where the
    // switch started: `autostart on|off` also notes the answer, so a first
    // "no" (the switch turned off while the tray is off anyway) counts; a
    // page left as it was is no answer
    if (loginWorks()) {
      const now = await J("autostart", "--json");
      const isOn = "on" in now ? !!now.on : !!(S.status.autostart || {}).on;
      if (W.login !== isOn || W.login !== W.loginFirst) await run(["autostart", W.login ? "on" : "off"]);
    }
    W.adopted = ((r.json || {}).adopted || []).length;
    await refresh();
    W.page = "done"; paint();
  };
  function paint() {
    const b = clear(s.body), f = clear(s.foot);
    const chosenRoots = W.roots.filter((r) => r.chosen).map((r) => r.path);
    const wrap = h("div", { class: "welcome stack" });
    b.append(wrap);
    if (W.page === "hello") {
      wrap.append(h("h1", { text: "∞  Welcome to aht" }),
        h("p", { text: "aht keeps the history of your AI coding agents (Claude Code, Codex, Gemini CLI and others) connected to your project folders." }),
        h("div", { class: "bullets" }, bullet("📁", "When you move, rename or copy a project folder, its agent history comes along."),
          bullet("🔎", "Find any session again: search, what changed, a journal, undo a whole session."),
          bullet("☰", "See every open session and the ones that wait for you."),
          bullet("🔒", "Everything stays on this computer. aht has no account and sends nothing anywhere unless you set that up.")),
        W.loading ? h("p", { class: "dim" }, h("span", { class: "spin" }), "Looking for your projects…") : null);
      f.append(h("button", { text: "Not Now", onclick: async () => { if (!again) await run(["setup", "--dismiss"]); closeSheet(); } }), h("span", { class: "spacer" }),
        h("button", { text: "Choose Each Step…", disabled: W.loading, onclick: () => { W.page = "folders"; paint(); } }),
        h("button", { class: "primary", text: "Quick Setup", disabled: W.loading, onclick: () => { W.page = "quick"; paint(); } }));
    } else if (W.page === "quick") {
      const take = W.projects.filter((p) => p.chosen), left = W.projects.filter((p) => p.forgotten && !p.chosen);
      wrap.append(h("h2", { text: "Quick Setup" }), h("p", { class: "dim", text: "aht will:" }),
        h("div", { class: "bullets" }, bullet("📁", "Watch " + names(chosenRoots) + "."),
          bullet("↺", take.length ? `Take on the ${plural(take.length, "project")} there that already ${take.length === 1 ? "has" : "have"} agent history: ${names(take.map((p) => p.path), 3)}.`
            : W.projects.length ? "Take on new projects as you work in them." : "Take on new projects as you work in them (none with agent history yet)."),
          left.length ? bullet("○", `Leave out ${names(left.map((p) => p.path), 3)}: you told aht to forget ${left.length === 1 ? "it" : "them"}.`) : null,
          bullet("?", folderRules()),
          extrasLine() ? bullet("🏷", extrasLine()) : null,
          loginWorks() ? h("div", {}, h("span", { class: "i", text: "▣" }), loginLine("Start aht's tray when you log in.")) : null));
      f.append(...btns("hello", "Next", () => { W.quickly = true; W.page = "updates"; paint(); }));
    } else if (W.page === "folders") {
      wrap.append(h("h2", { text: "Which folders hold your projects?" }),
        h("p", { class: "dim", text: "aht notices moves, copies and new projects inside these folders. A project elsewhere keeps its history, but aht does not follow it when it moves." }),
        W.roots.map((r) => h("label", { class: "check" }, h("input", { type: "checkbox", checked: r.chosen, onchange: (e) => { r.chosen = e.target.checked; paint(); } }),
          h("span", { class: "mono", text: tilde(r.path) }), r.projects ? h("span", { class: "dim small", text: `${plural(r.projects, "project")} with agent history` }) : null)),
        (W.elsewhere || []).length ? h("p", { class: "dim small", text: "Also with history, outside these: " + names(W.elsewhere, 3) }) : null,
        h("button", { text: "Add Folder…", onclick: async () => {
          const p = await pickFolder("Watch this folder: aht notices moves, copies and new projects inside it");
          if (!p) return;
          const x = W.roots.find((r) => r.path === p);
          if (x) x.chosen = true; else W.roots.push({ path: p, chosen: true, projects: 0 });
          load(false);
        } }));
      f.append(...btns("hello", "Next", () => { W.page = "projects"; load(false); }, chosenRoots.length > 0));
    } else if (W.page === "projects") {
      wrap.append(h("h2", { text: "Projects aht found" }),
        h("p", { class: "dim", text: "These folders already have agent history. aht takes on the ones you tick, and new projects as you work in them." }),
        W.loading ? h("p", {}, h("span", { class: "spin" })) : !W.projects.length ? h("p", { class: "dim", text: "None yet in these folders." }) : null,
        W.projects.map((p) => h("label", { class: "check" }, h("input", { type: "checkbox", checked: p.chosen, onchange: (e) => { p.chosen = e.target.checked; } }),
          h("span", { class: "mono", text: tilde(p.path) }), h("span", { class: "dim small", text: [p.agents.join(", "), p.forgotten ? "you told aht to forget it" : ""].filter(Boolean).join(" · ") }))),
        W.projects.length ? h("div", { class: "row" }, h("button", { class: "small", text: "All", onclick: () => { W.projects.forEach((p) => { p.chosen = true; }); paint(); } }),
          h("button", { class: "small", text: "None", onclick: () => { W.projects.forEach((p) => { p.chosen = false; }); paint(); } })) : null);
      f.append(...btns("folders", "Next", () => { W.page = "rules"; paint(); }));
    } else if (W.page === "rules") {
      wrap.append(h("h2", { text: "When a folder changes" }), h("p", { class: "dim", text: "aht keeps the history with its folder. It can ask you first, or do it by itself." }),
        pol("A project folder moves", "moves", [["ask", "Ask me"], ["apply", "Relink automatically"], ["decline", "Never relink (remember the no)"], ["ignore", "Do nothing"]]),
        pol("A project folder is copied", "copies", [["ask", "Ask me"], ["duplicate", "Duplicate the history"], ["independent", "Fresh identity, no history"], ["ignore", "Do nothing"]]));
      f.append(...btns("projects", "Next", () => { W.page = "extras"; paint(); }));
    } else if (W.page === "extras") {
      wrap.append(h("h2", { text: "A few more" }), toggle("Badge project folders", "badges"), toggle("Back up the agents' histories once a day", "backups"),
        toggle("Show notices (a session waits for you, a long one is done)", "notifications"),
        loginWorks() ? loginLine("Start aht's tray when I log in") : null);
      f.append(...btns("rules", "Next", () => { W.quickly = false; W.page = "updates"; paint(); }));
    } else if (W.page === "updates") {
      // a step of its own, so nobody misses it: off until the person says yes
      wrap.append(h("h2", { text: "⭳  Stay up to date" }),
        h("p", { text: "aht gets new features and fixes regularly. Should it tell you when a new version is out?" }),
        h("div", { class: "bullets" }, bullet("🔔", "A notice says so, with what's new and an Upgrade button."),
          bullet("🌐", "To know, aht asks GitHub once a day which version is the latest. GitHub sees your computer's address and which version of aht you run; nothing else is sent."),
          bullet("⚙", "You can change this any time in Settings → This computer.")));
      f.append(h("button", { text: "Back", onclick: () => { W.page = W.quickly ? "quick" : "extras"; paint(); } }),
        h("span", { class: "spacer" }),
        h("button", { text: "No Thanks", onclick: () => { W.update = false; apply(); } }),
        h("button", { class: "primary", text: "Yes, Tell Me", onclick: () => { W.update = true; apply(); } }));
    } else if (W.page === "working") {
      wrap.append(h("h2", { text: "Setting up aht" }), W.failed ? h("div", {}, h("p", { class: "warn", text: "That did not work:" }), h("pre", { text: W.failed }))
        : h("p", { class: "dim" }, h("span", { class: "spin" }), W.working));
      if (W.failed) f.append(h("button", { text: "Close", onclick: closeSheet }), h("span", { class: "spacer" }), h("button", { class: "primary", text: "Try Again", onclick: apply }));
    } else if (W.page === "done") {
      wrap.append(h("h2", { text: "✓  aht is set up" }),
        h("p", { class: "dim", text: `Watching ${names(chosenRoots)}; ${W.adopted ? `took on ${plural(W.adopted, "project")}` : "projects are taken on as you work in them"}.` }));
      const steps = S.status.getting_started || [];
      if (steps.length) {
        wrap.append(h("h3", { text: "Getting started: what lets aht do more" }));
        for (const x of steps) wrap.append(h("div", { class: "row top" }, h("span", { class: x.ok ? "okc" : x.optional ? "dim" : "warn", text: x.ok ? "✓" : x.optional ? "○" : "!" }),
          h("div", { class: "grow" }, h("strong", { text: x.title }), h("div", { class: "dim small", text: x.text + (x.how ? " " + x.how : "") }))));
      }
      f.append(helpBtn("Getting started"), h("span", { class: "spacer" }), h("button", { class: "primary", text: "Done", onclick: () => { closeSheet(); draw(); } }));
    }
  }
  paint();
  load(true);
}

// ---- start ------------------------------------------------------------------------

/** The window opened for one project (the tray's Projects brought here ▸
 * Send Back…): that project picked, and with "send-back" Send Back's dry
 * run open; a folder not in the list still gets Send Back. */
function openOn(go) {
  const p = S.projects.find((x) => sameDir(x.real_path, go.path));
  S.tab = "projects";
  if (p) S.selection = p.real_path;
  drawTop(); draw();
  // the project of a PC that does not answer goes back from the PC: its line says so
  if (go.do === "send-back" && !(p && pcHomeMute(copyOf(p)))) sendBack(p || { real_path: go.path, exists: true });
}
async function start() {
  $("#guide-btn").addEventListener("click", () => openGuide(null));
  drawTop(); draw();
  await refresh();
  const st = S.status;
  if (GO) openOn(GO);
  else if (!st.setup_done && (st.tracked || 0) <= 2 && !st.setup_dismissed) showWelcome(false);
  setInterval(() => { if (!LOST && !document.hidden && $("#sheet-back").hidden) refresh(); }, 20000);
  document.addEventListener("visibilitychange", () => { if (!LOST && !document.hidden) refresh(); });
  // the server stops after a while without a request: while this page is
  // open, whatever it shows, it asks once a minute
  setInterval(() => { if (!LOST) get("/api/ping"); }, 60000);
}
start();
