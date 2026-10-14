// LoCal front end. Plain ES modules, no build step.

const MEALS = ["breakfast", "lunch", "dinner", "snack"];
const MEAL_LABEL = { breakfast: "Breakfast", lunch: "Lunch", dinner: "Dinner", snack: "Snacks" };
const SOURCE_LABEL = { custom: "Yours", recipe: "Recipe", off: "Barcode", slv: "Livsmedelsverket", usda: "USDA", photo: "Photo", mealie: "Mealie" };
const PROVIDER_LABEL = { ollama: "Ollama (local)", anthropic: "Claude", openai: "OpenAI" };

const state = { user: null, settings: null, date: todayISO() };
const view = document.getElementById("view");

// Running inside the LoCal iPhone app? Its native features are reached through Capacitor's bridge.
const NATIVE = window.Capacitor?.isNativePlatform?.() ? window.Capacitor : null;
const native = (method, options = {}) => NATIVE.nativePromise("LocalTrackerNative", method, options);

// Running as a Home Assistant panel? The panel (ha-panel.js) hands us its `hass` object, and all
// requests go over Home Assistant's own websocket, signed in as the HA user.
const HA_MODE = new URLSearchParams(location.search).has("ha");
let HASS = null;
let hassReady;
const hassPromise = new Promise((r) => (hassReady = r));
window.__localTrackerSetHass = (h) => {
  const first = !HASS;
  HASS = h;
  if (first) hassReady(h);
};

/** Home Assistant app's built-in barcode scanner, when we're inside the HA phone app. */
function haScanner() {
  const ext = HASS?.auth?.external;
  return ext?.config?.hasBarCodeScanner ? ext : null;
}
function haScan() {
  return new Promise((resolve, reject) => {
    const ext = haScanner();
    const previous = ext._commandHandler;  // the app supports one handler, so pass everything else on
    const restore = () => { ext._commandHandler = previous; };
    ext._commandHandler = (msg) => {
      if (msg.command === "bar_code/scan_result") {
        restore();
        ext.fireMessage({ type: "bar_code/close" });
        resolve({ code: String(msg.payload?.rawValue || "") });
        return true;
      }
      if (msg.command === "bar_code/aborted") {
        restore();
        const manual = msg.payload?.reason === "alternative_options";
        reject(Object.assign(new Error(manual ? "Type the number" : "Scanning was cancelled."), { code: manual ? "manual" : "cancelled" }));
        return true;
      }
      return previous ? previous(msg) : false;
    };
    ext.fireMessage({ type: "bar_code/scan", payload: {
      title: "Scan a barcode", description: "Point the camera at the barcode on the package",
      alternative_option_label: "Type the number instead" } });
  });
}
// Which native scanner to use, if any: the LoCal iPhone app's or the Home Assistant app's.
const nativeScan = () => (NATIVE ? native("scanBarcode") : haScanner() ? haScan() : null);
const hasNativeScan = () => !!(NATIVE || haScanner());

const blobToBase64 = (blob) => new Promise((resolve, reject) => {
  const r = new FileReader();
  r.onload = () => resolve(String(r.result).split(",", 2)[1] || "");
  r.onerror = () => reject(r.error);
  r.readAsDataURL(blob);
});

async function haRequest(path, { method = "GET", body, form, raw } = {}) {
  const hass = HASS || await hassPromise;
  const msg = { type: "local_tracker/request", method, path };
  if (form) {
    msg.form = { fields: {}, files: {} };
    for (const [k, v] of form.entries()) {
      if (v instanceof Blob) msg.form.files[k] = { name: v.name || "upload.jpg", type: v.type || "application/octet-stream", data: await blobToBase64(v) };
      else msg.form.fields[k] = String(v);
    }
  } else if (body !== undefined) {
    msg.body = body;
  }
  const res = await hass.connection.sendMessagePromise(msg);
  if (raw) return res;
  if (res.status >= 400) throw new Error(res.json?.detail || `Request failed (${res.status})`);
  return res.json;
}

// ---------------------------------------------------------------- small utilities

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const r0 = (n) => Math.round(n || 0);
const r1 = (n) => Math.round((n || 0) * 10) / 10;
const fmt = (n) => r0(n).toLocaleString("sv-SE");

function todayISO() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}
function addDays(iso, n) {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}
function fmtDay(iso, relative = true) {
  if (relative) {
    if (iso === todayISO()) return "Today";
    if (iso === addDays(todayISO(), -1)) return "Yesterday";
    if (iso === addDays(todayISO(), 1)) return "Tomorrow";
  }
  return new Date(iso + "T12:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}
function mondayOf(iso) {
  const d = new Date(iso + "T12:00:00");
  return addDays(iso, -((d.getDay() + 6) % 7));
}
function defaultMeal() {
  const h = new Date().getHours();
  return h < 10 ? "breakfast" : h < 14 ? "lunch" : h < 17 ? "snack" : h < 21 ? "dinner" : "snack";
}
function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
const ICON = {
  left: '<svg class="i" viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg>',
  right: '<svg class="i" viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg>',
  plus: '<svg class="i" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  close: '<svg class="i" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  search: '<svg class="i" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>',
  barcode: '<svg class="i" viewBox="0 0 24 24"><path d="M4 6v12M7 6v12M11 6v12M14 6v12M17 6v12M20 6v12"/></svg>',
  camera: '<svg class="i" viewBox="0 0 24 24"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
  copy: '<svg class="i" viewBox="0 0 24 24"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/></svg>',
};

async function api(path, { method = "GET", body, form } = {}) {
  if (HA_MODE) return haRequest(path, { method, body, form });
  const opts = { method, headers: {}, credentials: "same-origin" };
  if (form) opts.body = form;
  else if (body !== undefined) {
    opts.body = JSON.stringify(body);
    opts.headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (res.status === 401 && !path.startsWith("/api/auth")) {
    state.user = null;
    renderAuth(false);
    throw new Error("Signed out");
  }
  if (!res.ok) throw new Error(data?.detail || `Request failed (${res.status})`);
  return data;
}

let toastTimer;
function toast(msg, err = false) {
  $(".toast")?.remove();
  const t = el(`<div class="toast${err ? " err" : ""}" role="status">${esc(msg)}</div>`);
  document.body.append(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), err ? 5000 : 2600);
}
const fail = (e) => e.message !== "Signed out" && toast(e.message, true);

// ---------------------------------------------------------------- sheets

function openSheet() {
  const scrim = el('<div class="scrim"></div>');
  const sheet = el('<section class="sheet" role="dialog" aria-modal="true"><div class="grab"></div><div class="sheet-body"></div></section>');
  const cleanups = [];
  const api_ = {
    el: sheet,
    body: $(".sheet-body", sheet),
    onClose: (fn) => cleanups.push(fn),
    set(title, content, back) {
      api_.runCleanups();
      api_.body.replaceChildren(el(`<div class="sheet-head">
          ${back ? `<button class="icon-btn" data-back aria-label="Back">${ICON.left}</button>` : ""}
          <h2 style="flex:1">${esc(title)}</h2>
          <button class="icon-btn" data-close aria-label="Close">${ICON.close}</button></div>`));
      if (back) $("[data-back]", api_.body).onclick = back;
      $("[data-close]", api_.body).onclick = api_.close;
      api_.body.append(content);
      sheet.scrollTop = 0;
    },
    runCleanups() { while (cleanups.length) { try { cleanups.pop()(); } catch { /* ignore */ } } },
    close() {
      api_.runCleanups();
      scrim.remove();
      sheet.remove();
      document.removeEventListener("keydown", onKey);
    },
  };
  const onKey = (e) => e.key === "Escape" && api_.close();
  scrim.onclick = api_.close;
  document.addEventListener("keydown", onKey);
  document.body.append(scrim, sheet);
  return api_;
}

// ---------------------------------------------------------------- auth

function renderAuth(needsSetup) {
  $("#tabs").classList.add("hidden");
  view.replaceChildren(el(`<div class="auth">
    <img class="mark" src="/static/icon.svg" alt="">
    <h1>${needsSetup ? "Set up LoCal" : "Sign in"}</h1>
    <p class="muted">${needsSetup ? "Create the first account. It becomes the admin who can add the rest of the household." : "Sign in to your household's LoCal."}</p>
    <form>
      <label class="field"><span>Username</span><input name="username" autocomplete="username" required autocapitalize="none"></label>
      <label class="field"><span>Password</span><input name="password" type="password" autocomplete="${needsSetup ? "new-password" : "current-password"}" required minlength="6"></label>
      <button class="btn block" type="submit">${needsSetup ? "Create account" : "Sign in"}</button>
    </form></div>`));
  $("form", view).onsubmit = async (e) => {
    e.preventDefault();
    const fd = Object.fromEntries(new FormData(e.target));
    try {
      const res = await api(needsSetup ? "/api/auth/setup" : "/api/auth/login", { method: "POST", body: fd });
      state.user = res.user;
      await loadSettings();
      route();
    } catch (err) { fail(err); }
  };
}

async function loadSettings() {
  state.settings = await api("/api/settings");
}

// ---------------------------------------------------------------- today

async function renderToday() {
  const date = state.date;
  const [diary, hist, plan] = await Promise.all([
    api(`/api/diary?date=${date}`),
    api(`/api/diary/history?end=${date}&days=7`),
    api(`/api/plan?start=${date}&days=1`),
  ]);
  const g = diary.goals, t = diary.totals;
  const left = g.kcal - t.kcal, over = left < 0;
  const frac = Math.min(t.kcal / (g.kcal || 1), 1);
  const C = 2 * Math.PI * 100;
  const planned = MEALS.flatMap((m) => plan.days[date][m]);

  const root = el(`<div>
    <div class="topbar">
      <div class="datepager">
        <button class="icon-btn" data-day="-1" aria-label="Previous day">${ICON.left}</button>
        <button class="date-label" aria-label="Pick a date">${esc(fmtDay(date))}</button>
        <button class="icon-btn" data-day="1" aria-label="Next day">${ICON.right}</button>
        <input type="date" class="hidden" value="${date}">
      </div>
      ${date !== todayISO() ? '<button class="btn plain" data-today>Back to today</button>' : ""}
    </div>
    <div class="plate-wrap">
      <svg class="plate" viewBox="0 0 240 240" aria-hidden="true">
        <circle class="rim" cx="120" cy="120" r="114"/>
        <circle class="well" cx="120" cy="120" r="88"/>
        <circle class="track" cx="120" cy="120" r="100"/>
        <circle class="fill${over ? " over" : ""}" cx="120" cy="120" r="100" transform="rotate(-90 120 120)"
          stroke-dasharray="${C * frac} ${C}"/>
      </svg>
      <div class="plate-center">
        <div class="big num${over ? " over" : ""}">${fmt(Math.abs(left))}</div>
        <div class="sub">${over ? "kcal over" : "kcal left"}</div>
        <div class="sub small num">${fmt(t.kcal)} of ${fmt(g.kcal)} eaten</div>
      </div>
    </div>
    <div class="macros">
      ${["protein", "carbs", "fat"].map((k) => `<div class="macro ${k}">
        <div class="name">${k[0].toUpperCase() + k.slice(1)}</div>
        <div class="bar"><i style="width:${Math.min(100, (t[k] / (g[k] || 1)) * 100)}%"></i></div>
        <div class="val num">${r0(t[k])} of ${r0(g[k])} g</div></div>`).join("")}
    </div>
    ${planned.length ? `<div class="callout row" style="justify-content:space-between">
        <span>${planned.length} planned item${planned.length > 1 ? "s" : ""} for ${esc(fmtDay(date).toLowerCase())}</span>
        <button class="btn ghost" style="flex:0" data-logplan>Log plan</button></div>` : ""}
    <div data-meals></div>
    <div class="row" style="justify-content:center">
      <button class="btn plain" style="flex:0" data-copy>${ICON.copy} Copy the day before</button>
    </div>
    <div class="week" aria-label="Last 7 days"></div>
  </div>`);

  const meals = $("[data-meals]", root);
  for (const m of MEALS) {
    const md = diary.meals[m];
    const sec = el(`<section class="meal" aria-label="${MEAL_LABEL[m]}">
      <div class="meal-head"><div><h2 style="display:inline">${MEAL_LABEL[m]}</h2>
        <span class="kc num">${md.entries.length ? fmt(md.totals.kcal) + " kcal" : ""}</span></div>
        <button class="icon-btn" aria-label="Add to ${MEAL_LABEL[m]}">${ICON.plus}</button></div>
      ${md.entries.length ? "" : '<div class="empty">Nothing logged yet</div>'}
    </section>`);
    $(".meal-head button", sec).onclick = () => openAdd({ date, meal: m, mode: "diary" });
    for (const e of md.entries) {
      const row = el(`<button class="item">
        <div class="main"><div class="title">${esc(e.food.name)}</div>
        <div class="meta num">${r0(e.grams)} g${e.food.brand && e.food.source !== "slv" ? " · " + esc(e.food.brand) : ""}</div></div>
        <div class="kcal num">${fmt(e.kcal)}</div></button>`);
      row.onclick = () => editEntry(e, date);
      sec.append(row);
    }
    meals.append(sec);
  }

  // Week strip
  const week = $(".week", root);
  const max = Math.max(hist.goal * 1.25, ...hist.days.map((d) => d.kcal), 1);
  week.append(el(`<div class="goal" style="bottom:${(hist.goal / max) * 70 + 20}px" title="Goal"></div>`));
  for (const d of hist.days) {
    const col = el(`<div class="d"><div class="col${d.kcal > hist.goal ? " over" : ""}${d.date === date ? " today" : ""}"
      style="height:${(d.kcal / max) * 70}px" title="${fmt(d.kcal)} kcal"></div>
      <div class="lbl">${new Date(d.date + "T12:00").toLocaleDateString("en-GB", { weekday: "narrow" })}</div></div>`);
    col.onclick = () => { state.date = d.date; renderToday(); };
    week.append(col);
  }

  $$("[data-day]", root).forEach((b) => (b.onclick = () => { state.date = addDays(date, +b.dataset.day); renderToday(); }));
  const picker = $('input[type="date"]', root);
  $(".date-label", root).onclick = () => (picker.showPicker ? picker.showPicker() : picker.classList.remove("hidden"));
  picker.onchange = () => { if (picker.value) { state.date = picker.value; renderToday(); } };
  $("[data-today]", root)?.addEventListener("click", () => { state.date = todayISO(); renderToday(); });
  $("[data-copy]", root).onclick = async () => {
    try {
      await api("/api/diary/copy", { method: "POST", body: { from: addDays(date, -1), to: date } });
      toast("Copied the day before");
      renderToday();
    } catch (e) { fail(e); }
  };
  $("[data-logplan]", root)?.addEventListener("click", async () => {
    try {
      const res = await api("/api/plan/log", { method: "POST", body: { date } });
      toast(`Logged ${res.logged} planned item${res.logged === 1 ? "" : "s"}`);
      renderToday();
    } catch (e) { fail(e); }
  });
  view.replaceChildren(root);
  syncHealth(date, diary.totals);
}

// ---------------------------------------------------------------- Apple Health (iPhone app only)

const healthKey = () => `local-tracker.health.${location.host}.${state.user?.id}`;
function healthEnabled() {
  try { return !!NATIVE && localStorage.getItem(healthKey()) === "1"; } catch { return false; }
}

/** Saves a day's totals to Apple Health. Skips the write when nothing changed since last time. */
async function syncHealth(date, totals, force = false) {
  if (!healthEnabled()) return;
  const sig = JSON.stringify([totals.kcal, totals.protein, totals.carbs, totals.fat, totals.fiber]);
  const cacheKey = `${healthKey()}.${date}`;
  try { if (!force && localStorage.getItem(cacheKey) === sig) return; } catch { /* ignore */ }
  try {
    await native("healthSaveDay", { date, user: `${location.host}-${state.user.id}`, ...totals });
    try { localStorage.setItem(cacheKey, sig); } catch { /* ignore */ }
  } catch (e) {
    if (e?.code === "denied") toast(e.message, true);
  }
}

async function enableHealth() {
  const res = await native("healthRequest");
  if (!res?.allowed) throw new Error("Apple Health access wasn't allowed. You can turn it on in the Health app → Sharing → Apps → LoCal.");
  localStorage.setItem(healthKey(), "1");
  // Fill in the last week so Health isn't empty.
  for (let i = 0; i < 7; i++) {
    const d = addDays(todayISO(), -i);
    const diary = await api(`/api/diary?date=${d}`);
    await syncHealth(d, diary.totals, true);
  }
}

function editEntry(e, date) {
  const sheet = openSheet();
  amountPanel(sheet, e.food, {
    title: "Edit entry", grams: e.grams, meal: e.meal, showMeal: true, action: "Save changes",
    extra: (box) => {
      const del = el('<button class="btn danger block" style="margin-top:8px">Remove from diary</button>');
      del.onclick = async () => {
        try { await api(`/api/entries/${e.id}`, { method: "DELETE" }); sheet.close(); toast("Removed"); renderToday(); }
        catch (err) { fail(err); }
      };
      box.append(del);
    },
    onDone: async (grams, meal) => {
      await api(`/api/entries/${e.id}`, { method: "PUT", body: { grams, meal, date } });
      sheet.close();
      toast("Saved");
      renderToday();
    },
  });
}

// ---------------------------------------------------------------- adding food

/**
 * The add sheet: search, scan or photo. Modes:
 *  diary  - logs into state.user's diary for date/meal
 *  plan   - adds to the shared meal plan
 *  recipe - returns {food, grams} to opts.onPick
 */
function openAdd(opts) {
  const sheet = openSheet();
  opts = { mode: "diary", date: state.date, meal: defaultMeal(), ...opts };
  showAddHome(sheet, opts, opts.tab || "search");
  return sheet;
}

function addTitle(opts) {
  if (opts.mode === "recipe") return "Add ingredient";
  if (opts.mode === "plan") return `Plan for ${fmtDay(opts.date)}`;
  return `${MEAL_LABEL[opts.meal]} · ${fmtDay(opts.date)}`;
}

function showAddHome(sheet, opts, tab) {
  const tabs = [["search", "Search", ICON.search], ["scan", "Scan", ICON.barcode]];
  if (opts.mode === "diary") tabs.push(["photo", "Photo", ICON.camera]);
  const box = el(`<div><div class="seg" role="tablist">${tabs.map(([k, l, i]) =>
    `<button role="tab" data-t="${k}" class="${k === tab ? "on" : ""}">${i}${l}</button>`).join("")}</div><div data-panel></div></div>`);
  sheet.set(addTitle(opts), box);
  $$("[data-t]", box).forEach((b) => (b.onclick = () => showAddHome(sheet, opts, b.dataset.t)));
  const panel = $("[data-panel]", box);
  if (tab === "search") searchPanel(sheet, opts, panel);
  if (tab === "scan") scanPanel(sheet, opts, panel);
  if (tab === "photo") photoPanel(sheet, opts, panel);
}

function foodRow(f, extraMeta = "") {
  const b = el(`<button class="item">
    <div class="main"><div class="title">${esc(f.name)}</div>
    <div class="meta"><span class="src">${esc(SOURCE_LABEL[f.source] || f.source)}</span>${f.brand && f.source !== "slv" && f.source !== "recipe" ? esc(f.brand) + " · " : ""}${extraMeta}</div></div>
    <div class="kcal num">${fmt(f.kcal)}<span class="muted small"> /100 g</span></div></button>`);
  return b;
}

function searchPanel(sheet, opts, panel) {
  panel.append(el(`<div>
    <input type="search" placeholder="Search foods and recipes" aria-label="Search foods" enterkeyhint="search" autocomplete="off">
    <div data-results></div>
    <div data-remote></div>
    <div class="chips" style="margin-top:14px">
      <button class="chip" data-remote-src="off">Search Open Food Facts</button>
      <button class="chip" data-remote-src="usda">Search USDA</button>
      <button class="chip" data-create>Create a food</button>
    </div></div>`));
  const input = $("input", panel), results = $("[data-results]", panel), remote = $("[data-remote]", panel);

  const show = (title, foods, onPick, empty) => {
    const wrap = el(`<div><div class="list-title">${esc(title)}</div><div class="list"></div></div>`);
    if (!foods.length) $(".list", wrap).append(el(`<div class="empty" style="padding-top:12px">${esc(empty)}</div>`));
    for (const f of foods) {
      const row = foodRow(f, f.last_grams ? `last ${r0(f.last_grams)} g` : "");
      row.onclick = () => onPick(f);
      $(".list", wrap).append(row);
    }
    return wrap;
  };
  const pick = (f) => amountForAdd(sheet, opts, f, () => showAddHome(sheet, opts, "search"));

  const run = async () => {
    const q = input.value.trim();
    remote.replaceChildren();
    try {
      if (!q) {
        const recent = await api("/api/foods/recent");
        results.replaceChildren(show("Recent", recent, pick, "Foods you log show up here."));
      } else {
        const found = await api(`/api/foods/search?q=${encodeURIComponent(q)}`);
        results.replaceChildren(show("In your database", found, pick, "No matches. Try the online databases below, or create the food."));
      }
    } catch (e) { fail(e); }
  };
  input.oninput = debounce(run, 180);
  run();
  setTimeout(() => input.focus(), 60);

  $$("[data-remote-src]", panel).forEach((b) => (b.onclick = async () => {
    const q = input.value.trim();
    if (!q) { input.focus(); return toast("Type what you're looking for first"); }
    const src = b.dataset.remoteSrc;
    remote.replaceChildren(el('<div class="empty"><span class="spinner"></span> Searching…</div>'));
    try {
      const foods = await api(`/api/foods/remote/${src}?q=${encodeURIComponent(q)}`);
      remote.replaceChildren(show(src === "usda" ? "USDA FoodData Central" : "Open Food Facts", foods, async (f) => {
        try { pick(await api("/api/foods/import", { method: "POST", body: f })); } catch (e) { fail(e); }
      }, "Nothing found there."));
    } catch (e) {
      remote.replaceChildren(el(`<div class="callout warn">${esc(e.message)}</div>`));
    }
  }));
  $("[data-create]", panel).onclick = () =>
    foodForm(sheet, { name: input.value.trim() }, (f) => pick(f), () => showAddHome(sheet, opts, "search"));
}

function amountForAdd(sheet, opts, food, back) {
  const action = opts.mode === "recipe" ? "Add to recipe" : opts.mode === "plan" ? "Add to plan" : "Add to diary";
  amountPanel(sheet, food, {
    title: food.name, back, meal: opts.meal, showMeal: opts.mode !== "recipe", action,
    onDone: async (grams, meal) => {
      if (opts.mode === "recipe") { opts.onPick({ food, grams }); sheet.close(); return; }
      if (opts.mode === "plan") {
        await api("/api/plan", { method: "POST", body: { date: opts.date, meal, food_id: food.id, grams } });
        toast(`Planned ${food.name}`);
      } else {
        await api("/api/entries", { method: "POST", body: { date: opts.date, meal, food_id: food.id, grams } });
        toast(`Added ${food.name}`);
      }
      sheet.close();
      opts.onDone ? opts.onDone() : route();
    },
  });
}

/** Grams picker with a live nutrition preview. */
function amountPanel(sheet, food, { title, grams, meal, showMeal, action, back, onDone, extra }) {
  const start = grams || food.last_grams || food.serving_g || 100;
  const chips = [...new Set([food.serving_g, 50, 100, 150, 200, 250].filter(Boolean).map(r0))];
  const box = el(`<form>
    <p class="muted" style="margin:0 0 10px">${esc([SOURCE_LABEL[food.source], food.brand && food.source !== "slv" ? food.brand : ""].filter(Boolean).join(" · "))}
      · <span class="num">${fmt(food.kcal)}</span> kcal per 100 g</p>
    <div class="amount-big"><input type="number" inputmode="decimal" min="0.1" step="any" value="${r1(start)}" aria-label="Grams" required><span class="muted">grams</span></div>
    <div class="chips">${chips.map((c) => `<button type="button" class="chip" data-g="${c}">${c === r0(food.serving_g) ? `1 serving (${c} g)` : c + " g"}</button>`).join("")}</div>
    <div class="preview num"></div>
    ${showMeal ? `<label class="field"><span>Meal</span><select name="meal">${MEALS.map((m) => `<option value="${m}" ${m === meal ? "selected" : ""}>${MEAL_LABEL[m]}</option>`).join("")}</select></label>` : ""}
    <button class="btn block" type="submit">${esc(action)}</button>
    ${food.source === "custom" || food.source === "photo" ? '<button type="button" class="btn plain block" data-editfood>Edit this food</button>' : ""}
    ${food.recipe_id ? '<button type="button" class="btn plain block" data-openrecipe>Open recipe</button>' : ""}
  </form>`);
  const input = $("input", box), prev = $(".preview", box);
  const upd = () => {
    const g = parseFloat(input.value) || 0;
    prev.innerHTML = [["kcal", "kcal"], ["protein", "protein"], ["carbs", "carbs"], ["fat", "fat"]]
      .map(([k, l]) => `<div><b>${k === "kcal" ? fmt((food[k] * g) / 100) : r1((food[k] * g) / 100)}</b><span>${l}${k === "kcal" ? "" : " g"}</span></div>`).join("");
    $$("[data-g]", box).forEach((c) => c.classList.toggle("on", +c.dataset.g === g));
  };
  input.oninput = upd;
  $$("[data-g]", box).forEach((c) => (c.onclick = () => { input.value = c.dataset.g; upd(); }));
  upd();
  box.onsubmit = async (e) => {
    e.preventDefault();
    const btn = $('button[type="submit"]', box);
    btn.disabled = true;
    try { await onDone(parseFloat(input.value), showMeal ? $("select", box).value : meal); }
    catch (err) { fail(err); btn.disabled = false; }
  };
  $("[data-editfood]", box)?.addEventListener("click", () =>
    foodForm(sheet, food, (f) => amountPanel(sheet, f, { title, grams, meal, showMeal, action, back, onDone, extra }),
      () => amountPanel(sheet, food, { title, grams, meal, showMeal, action, back, onDone, extra })));
  $("[data-openrecipe]", box)?.addEventListener("click", () => { sheet.close(); location.hash = `#/recipe/${food.recipe_id}`; });
  extra?.(box);
  sheet.set(title, box, back);
  setTimeout(() => { input.focus(); input.select(); }, 60);
}

/** Create or edit a food from its label values. */
function foodForm(sheet, food, onSaved, back, notice = "") {
  const f = { kcal: "", protein: "", carbs: "", fat: "", fiber: "", ...food };
  const v = (k) => (f[k] === null || f[k] === undefined ? "" : esc(f[k]));
  const box = el(`<form>
    ${notice ? `<div class="callout">${esc(notice)}</div>` : ""}
    <label class="field"><span>Name</span><input name="name" required value="${v("name")}"></label>
    <div class="grid2">
      <label class="field"><span>Brand</span><input name="brand" value="${v("brand")}"></label>
      <label class="field"><span>Barcode</span><input name="barcode" inputmode="numeric" value="${v("barcode")}"></label>
    </div>
    <p class="hint">Values per 100 g, as printed on the label.</p>
    <div class="grid2">
      <label class="field"><span>Energy (kcal)</span><input name="kcal" type="number" step="any" min="0" inputmode="decimal" required value="${v("kcal")}"></label>
      <label class="field"><span>Protein (g)</span><input name="protein" type="number" step="any" min="0" inputmode="decimal" value="${v("protein")}"></label>
      <label class="field"><span>Carbohydrates (g)</span><input name="carbs" type="number" step="any" min="0" inputmode="decimal" value="${v("carbs")}"></label>
      <label class="field"><span>Fat (g)</span><input name="fat" type="number" step="any" min="0" inputmode="decimal" value="${v("fat")}"></label>
      <label class="field"><span>Fibre (g)</span><input name="fiber" type="number" step="any" min="0" inputmode="decimal" value="${v("fiber")}"></label>
      <label class="field"><span>Serving size (g)</span><input name="serving_g" type="number" step="any" min="0" inputmode="decimal" value="${v("serving_g")}"></label>
    </div>
    <p class="hint">Label only lists kJ? Divide by 4.184 to get kcal.</p>
    <button class="btn block" type="submit" style="margin-top:12px">${food.id ? "Save food" : "Create food"}</button>
  </form>`);
  box.onsubmit = async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(box));
    try {
      const saved = food.id
        ? await api(`/api/foods/${food.id}`, { method: "PUT", body: data })
        : await api("/api/foods", { method: "POST", body: data });
      toast(food.id ? "Food saved" : "Food created");
      onSaved(saved);
    } catch (err) { fail(err); }
  };
  sheet.set(food.id ? "Edit food" : "New food", box, back);
}

// ---------------------------------------------------------------- barcode scanning

const BARCODE_FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128"];

async function makeDetector() {
  if ("BarcodeDetector" in window) {
    try {
      const supported = await window.BarcodeDetector.getSupportedFormats();
      const formats = BARCODE_FORMATS.filter((f) => supported.includes(f));
      if (formats.length) {
        const d = new window.BarcodeDetector({ formats });
        return { detect: async (src) => (await d.detect(src))[0]?.rawValue };
      }
    } catch { /* fall through */ }
  }
  return null;
}

function scanPanel(sheet, opts, panel) {
  const NATIVE_SCAN = hasNativeScan();
  const live = !NATIVE_SCAN && window.isSecureContext && navigator.mediaDevices?.getUserMedia;
  panel.append(el(`<div>
    ${NATIVE_SCAN ? `<button class="btn block" data-native-scan>${ICON.barcode} Open the scanner</button>`
      : live ? '<div class="scanner"><video playsinline muted></video><div class="aim"></div></div><p class="hint" data-status>Point the camera at the barcode.</p>'
      : `<div class="callout">The live scanner needs the app to be opened over HTTPS. You can still take a photo of the barcode.</div>`}
    <label class="btn ghost block${NATIVE_SCAN ? " hidden" : ""}" style="margin-top:10px">${ICON.camera} Take a photo of the barcode
      <input type="file" accept="image/*" capture="environment" class="hidden"></label>
    <form class="row" style="margin-top:12px">
      <input inputmode="numeric" placeholder="Or type the number" aria-label="Barcode number" pattern="[0-9 ]{6,16}">
      <button class="btn" style="flex:0" type="submit">Look up</button>
    </form></div>`));

  let done = false;
  const onCode = async (code) => {
    if (done) return;
    done = true;
    navigator.vibrate?.(40);
    sheet.runCleanups();
    try {
      const res = await api(`/api/foods/barcode/${encodeURIComponent(code)}`);
      const back = () => showAddHome(sheet, opts, "scan");
      if (res.status === "ok") return amountForAdd(sheet, opts, res.food, back);
      const msg = {
        not_found: `Barcode ${res.barcode} isn't in Open Food Facts yet. Enter the values from the label and it's saved for next time.`,
        incomplete: `Open Food Facts has barcode ${res.barcode} but without calories. Enter the values from the label.`,
        offline: `Couldn't reach Open Food Facts. Enter the values from the label for barcode ${res.barcode}.`,
      }[res.status];
      foodForm(sheet, { barcode: res.barcode }, (f) => amountForAdd(sheet, opts, f, back), back, msg);
    } catch (e) { done = false; fail(e); }
  };

  $("form", panel).onsubmit = (e) => {
    e.preventDefault();
    const code = $("form input", panel).value.replace(/\D/g, "");
    if (code.length >= 6) onCode(code);
  };

  $('input[type="file"]', panel).onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const code = await decodeImageFile(file);
      if (code) onCode(code);
      else toast("No barcode found in that photo. Get closer and keep it sharp.", true);
    } catch (err) { fail(err); }
  };

  if (NATIVE_SCAN) {
    const openScanner = async () => {
      try {
        const res = await nativeScan();
        if (res?.code) onCode(res.code.replace(/\D/g, "") || res.code);
      } catch (e) {
        if (e?.code === "manual") $("form input", panel)?.focus();
        else if (e?.code !== "cancelled") toast(e?.message || "The scanner couldn't start", true);
      }
    };
    $("[data-native-scan]", panel).onclick = openScanner;
    openScanner();
  }
  if (live) startLiveScan(sheet, panel, onCode);
}

async function decodeImageFile(file) {
  const det = await makeDetector();
  if (det) {
    const bmp = await createImageBitmap(file);
    return det.detect(bmp);
  }
  if (window.ZXing) {
    const url = URL.createObjectURL(file);
    try {
      const reader = new window.ZXing.BrowserMultiFormatReader();
      return (await reader.decodeFromImageUrl(url)).getText();
    } catch { return null; } finally { URL.revokeObjectURL(url); }
  }
  throw new Error("This browser can't read barcodes. Type the number instead.");
}

async function startLiveScan(sheet, panel, onCode) {
  const video = $("video", panel), status = $("[data-status]", panel);
  const det = await makeDetector();
  if (!det && window.ZXing) {
    const reader = new window.ZXing.BrowserMultiFormatReader();
    sheet.onClose(() => reader.reset());
    reader.decodeFromConstraints({ video: { facingMode: "environment" } }, video, (res) => res && onCode(res.getText()))
      .catch((e) => (status.textContent = `Camera unavailable: ${e.message}`));
    return;
  }
  if (!det) {
    $(".scanner", panel).remove();
    status.textContent = "This browser can't scan barcodes live. Take a photo of the barcode or type the number.";
    return;
  }
  let stream, stopped = false;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1280 } } });
  } catch (e) {
    status.textContent = `Camera unavailable: ${e.message}. Take a photo or type the number instead.`;
    return;
  }
  sheet.onClose(() => { stopped = true; stream.getTracks().forEach((t) => t.stop()); });
  video.srcObject = stream;
  await video.play().catch(() => {});
  const loop = async () => {
    if (stopped) return;
    try {
      if (video.readyState >= 2) {
        const code = await det.detect(video);
        if (code) return onCode(code);
      }
    } catch { /* keep trying */ }
    setTimeout(loop, 180);
  };
  loop();
}

// ---------------------------------------------------------------- photo logging

async function shrinkImage(file, max = 1280) {
  const bmp = await createImageBitmap(file);
  const scale = Math.min(1, max / Math.max(bmp.width, bmp.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * scale);
  c.height = Math.round(bmp.height * scale);
  c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
  return new Promise((res) => c.toBlob(res, "image/jpeg", 0.85));
}

function photoPanel(sheet, opts, panel) {
  const providers = state.settings.photo_providers;
  if (!providers.length) {
    panel.append(el(`<div class="callout">Photo logging isn't set up yet. ${state.user.is_admin
      ? "Add a local Ollama server or an API key under You → Photo recognition."
      : "Ask the household admin to set it up under You → Photo recognition."}</div>`));
    return;
  }
  const def = providers.includes(state.settings.default_provider) ? state.settings.default_provider : providers[0];
  panel.append(el(`<div>
    <label class="btn block">${ICON.camera} Take a photo of your meal
      <input type="file" accept="image/*" capture="environment" class="hidden" data-shot></label>
    <label class="btn plain block">Choose from your photos<input type="file" accept="image/*" class="hidden" data-shot></label>
    <div data-after class="hidden">
      <img class="photo-preview" alt="Your meal">
      <label class="field"><span>Anything the photo doesn't show? (optional)</span>
        <input data-note placeholder="e.g. fried in butter, half a portion, 2 dl sauce"></label>
      ${providers.length > 1 ? `<label class="field"><span>Recognise with</span><select data-provider>${providers.map((p) =>
        `<option value="${p}" ${p === def ? "selected" : ""}>${PROVIDER_LABEL[p]}</option>`).join("")}</select></label>` : ""}
      <button class="btn block" data-go>Estimate calories</button>
    </div>
    <p class="hint">The estimate is a starting point. Check the amounts before logging.</p></div>`));
  let blob;
  $$("[data-shot]", panel).forEach((inp) => (inp.onchange = async () => {
    const f = inp.files[0];
    if (!f) return;
    blob = await shrinkImage(f).catch(() => f);
    $("img", panel).src = URL.createObjectURL(blob);
    $("[data-after]", panel).classList.remove("hidden");
  }));
  $("[data-go]", panel).onclick = async () => {
    const provider = $("[data-provider]", panel)?.value || def;
    const fd = new FormData();
    fd.append("image", blob, "meal.jpg");
    fd.append("note", $("[data-note]", panel).value);
    fd.append("provider", provider);
    const go = $("[data-go]", panel);
    go.disabled = true;
    go.innerHTML = `<span class="spinner"></span> Looking at your meal…`;
    const slow = provider === "ollama" ? setTimeout(() => toast("Local models can take a minute. Hang on."), 8000) : null;
    try {
      const res = await api("/api/photo/analyze", { method: "POST", form: fd });
      photoReview(sheet, opts, res, $("img", panel).src);
    } catch (e) {
      fail(e);
      go.disabled = false;
      go.textContent = "Try again";
    } finally { clearTimeout(slow); }
  };
}

function photoReview(sheet, opts, res, imgSrc) {
  const box = el(`<div>
    <img class="photo-preview" src="${imgSrc}" alt="" style="max-height:160px">
    ${res.description ? `<p class="muted" style="margin:4px 0">${esc(res.description)}</p>` : ""}
    ${res.items.length ? "" : '<div class="callout warn">No food recognised. Try a clearer photo, or search instead.</div>'}
    <div data-items></div>
    <div class="preview num" data-total></div>
    <label class="field"><span>Meal</span><select data-meal>${MEALS.map((m) => `<option value="${m}" ${m === opts.meal ? "selected" : ""}>${MEAL_LABEL[m]}</option>`).join("")}</select></label>
    <button class="btn block" data-log>Log meal</button></div>`);
  const items = res.items.map((it) => ({ ...it, use: "ai", on: true }));
  const list = $("[data-items]", box), total = $("[data-total]", box);
  const per100 = (it) => (it.use === "ai" ? it : it.matches.find((m) => String(m.id) === it.use));
  const recalc = () => {
    const t = { kcal: 0, protein: 0, carbs: 0, fat: 0 };
    items.forEach((it, i) => {
      const p = per100(it);
      const k = (p.kcal * it.grams) / 100;
      $(`[data-kcal="${i}"]`, list).textContent = `${fmt(k)} kcal`;
      if (it.on) for (const key in t) t[key] += ((p[key] || 0) * it.grams) / 100;
    });
    total.innerHTML = `<div><b>${fmt(t.kcal)}</b><span>kcal</span></div><div><b>${r1(t.protein)}</b><span>protein g</span></div>
      <div><b>${r1(t.carbs)}</b><span>carbs g</span></div><div><b>${r1(t.fat)}</b><span>fat g</span></div>`;
    $("[data-log]", box).disabled = !items.some((i) => i.on);
  };
  items.forEach((it, i) => {
    const row = el(`<div class="ai-item">
      <div class="top">
        <input type="checkbox" checked style="width:22px;min-height:22px;flex:0" aria-label="Include ${esc(it.name)}">
        <input data-name value="${esc(it.name)}" aria-label="Food name">
        <input data-grams class="g" type="number" inputmode="decimal" min="1" value="${it.grams}" aria-label="Grams">
        <span class="muted small">g</span>
      </div>
      <div class="row" style="margin-top:8px">
        <select data-use aria-label="Nutrition values to use">
          <option value="ai">Photo estimate · ${fmt(it.kcal)} kcal/100 g</option>
          ${it.matches.map((m) => `<option value="${m.id}">${esc(m.name)} · ${fmt(m.kcal)} kcal/100 g (${esc(SOURCE_LABEL[m.source])})</option>`).join("")}
        </select>
        <b class="num" style="flex:0;white-space:nowrap" data-kcal="${i}"></b>
      </div></div>`);
    $('input[type="checkbox"]', row).onchange = (e) => { it.on = e.target.checked; row.style.opacity = it.on ? 1 : 0.5; recalc(); };
    $("[data-name]", row).oninput = (e) => (it.name = e.target.value);
    $("[data-grams]", row).oninput = (e) => { it.grams = parseFloat(e.target.value) || 0; recalc(); };
    $("[data-use]", row).onchange = (e) => { it.use = e.target.value; recalc(); };
    list.append(row);
  });
  if (items.length) recalc();
  $("[data-log]", box).onclick = async () => {
    const chosen = items.filter((i) => i.on && i.grams > 0).map((it) => it.use === "ai"
      ? { name: it.name, grams: it.grams, kcal: it.kcal, protein: it.protein, carbs: it.carbs, fat: it.fat }
      : { food_id: +it.use, grams: it.grams });
    try {
      const r = await api("/api/photo/log", { method: "POST", body: { date: opts.date, meal: $("[data-meal]", box).value, items: chosen } });
      sheet.close();
      toast(`Logged ${r.logged} item${r.logged === 1 ? "" : "s"}`);
      route();
    } catch (e) { fail(e); }
  };
  sheet.set(`Photo · ${PROVIDER_LABEL[res.provider]}`, box, () => showAddHome(sheet, opts, "photo"));
}

// ---------------------------------------------------------------- recipes

async function renderRecipes() {
  const recipes = await api("/api/recipes");
  const root = el(`<div>
    <div class="topbar"><h1>Recipes</h1>
      <div class="row" style="flex:0;gap:8px"><button class="btn ghost" data-import>Import</button>
      <a class="btn" href="#/recipe/new">${ICON.plus} New</a></div></div>
    <p class="muted" style="margin-top:0">Shared with everyone in the household. Each recipe can be logged like any food, by the gram.</p>
    <div class="list"></div></div>`);
  const list = $(".list", root);
  if (!recipes.length) list.append(el('<div class="empty" style="padding:16px">No recipes yet. Add the ingredients of a dish you cook often, weigh the finished pot, and you’ll know the calories in every gram.</div>'));
  for (const r of recipes) {
    const row = el(`<a class="item" href="#/recipe/${r.id}" style="text-decoration:none;color:inherit">
      <div class="main"><div class="title">${esc(r.name)}</div>
      <div class="meta num">${r.mealie_slug ? '<span class="src">Mealie</span>' : ""}${r.n_items} ingredient${r.n_items === 1 ? "" : "s"}${r.serving_g ? ` · ${r0(r.serving_g)} g per serving` : ""}</div></div>
      <div class="kcal num">${fmt(r.kcal_per100)}<span class="muted small"> /100 g</span></div></a>`);
    list.append(row);
  }
  $("[data-import]", root).onclick = openImport;
  view.replaceChildren(root);
}

// ---------------------------------------------------------------- recipe import (link or Mealie)

function openImport(tab) {
  const sheet = openSheet();
  const hasMealie = !!state.settings.mealie?.configured;
  tab = typeof tab === "string" ? tab : "link";
  const box = el(`<div>
    ${hasMealie ? `<div class="seg"><button data-t="link" class="${tab === "link" ? "on" : ""}">From a link</button>
      <button data-t="mealie" class="${tab === "mealie" ? "on" : ""}">From Mealie</button></div>` : ""}
    <div data-panel></div></div>`);
  sheet.set("Import a recipe", box);
  $$("[data-t]", box).forEach((b) => (b.onclick = () => { sheet.close(); openImport(b.dataset.t); }));
  const panel = $("[data-panel]", box);
  const done = (draft) => { state.importDraft = draft; sheet.close(); location.hash = "#/recipe/import"; };

  if (tab === "link") {
    panel.append(el(`<form>
      <label class="field"><span>Recipe page</span>
        <input name="url" type="url" inputmode="url" autocapitalize="none" placeholder="https://www.ica.se/recept/…" required></label>
      <p class="hint">ICA, Arla, Köket, Coop and most other recipe sites work.</p>
      ${hasMealie ? '<label class="row" style="margin:12px 0;justify-content:flex-start;gap:10px"><input type="checkbox" name="via_mealie" checked style="flex:0;width:22px;min-height:22px"><span>Save in Mealie too</span></label>' : ""}
      <button class="btn block" type="submit">Import</button></form>`));
    $("form", panel).onsubmit = async (e) => {
      e.preventDefault();
      const btn = $('button[type="submit"]', panel);
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Reading the recipe…';
      try {
        done(await api("/api/import/url", { method: "POST", body: {
          url: e.target.url.value.trim(), via_mealie: !!e.target.via_mealie?.checked } }));
      } catch (err) { fail(err); btn.disabled = false; btn.textContent = "Import"; }
    };
    setTimeout(() => $("input", panel).focus(), 60);
  } else {
    panel.append(el(`<div><input type="search" placeholder="Search your Mealie recipes" aria-label="Search Mealie">
      <div class="list" style="margin-top:12px" data-list></div></div>`));
    const input = $("input", panel), list = $("[data-list]", panel);
    const run = async () => {
      list.replaceChildren(el('<div class="empty" style="padding:14px 16px"><span class="spinner"></span></div>'));
      try {
        const res = await api(`/api/mealie/recipes?q=${encodeURIComponent(input.value.trim())}`);
        list.replaceChildren();
        if (!res.length) list.append(el('<div class="empty" style="padding:14px 16px">No recipes found in Mealie.</div>'));
        for (const r of res) {
          const row = el(`<button class="item"><div class="main"><div class="title">${esc(r.name)}</div>
            <div class="meta">${esc(r.yield || (r.servings ? r.servings + " servings" : ""))}</div></div></button>`);
          row.onclick = async () => {
            row.disabled = true;
            try { done(await api("/api/mealie/import", { method: "POST", body: { slug: r.slug } })); }
            catch (err) { fail(err); row.disabled = false; }
          };
          list.append(row);
        }
      } catch (err) { list.replaceChildren(el(`<div class="callout warn">${esc(err.message)}</div>`)); }
    };
    input.oninput = debounce(run, 300);
    run();
  }
}

function renderImportReview() {
  const d = state.importDraft;
  if (!d) { location.hash = "#/recipes"; return; }
  const items = d.items.map((it) => ({ ...it, choice: it.skip || !it.food_id ? (it.skip ? "skip" : "") : String(it.food_id) }));
  const root = el(`<div>
    <div class="topbar"><a class="icon-btn" href="#/recipes" aria-label="Back to recipes">${ICON.left}</a><div style="flex:1"></div></div>
    <label class="field"><span>Recipe name</span><input data-name value="${esc(d.name)}" style="font-size:20px;font-weight:650"></label>
    <p class="muted small" style="margin-top:0">${d.mealie_slug ? "From Mealie" : ""}${d.mealie_slug && d.source_url ? " · " : ""}${d.source_url ? esc(new URL(d.source_url).hostname.replace(/^www\./, "")) : ""}</p>
    <h2 style="margin:16px 0 4px">Check the ingredients</h2>
    <p class="hint" style="margin-top:0">Pick the matching food and check the grams. Amounts in dl, pieces or packs are estimates.</p>
    <div data-items></div>
    <div class="grid2" style="margin-top:6px">
      <label class="field"><span>Cooked weight (g)</span><input data-final type="number" inputmode="decimal" min="1" step="any" placeholder="optional"></label>
      <label class="field"><span>Servings</span><input data-servings type="number" inputmode="decimal" min="0.1" step="any" value="${d.servings}"></label>
    </div>
    <p class="hint">Weigh the finished dish without the pot for exact kcal per gram. You can add it later too.</p>
    <div class="recipe-sum" data-sum></div>
    <button class="btn block" data-save>Create recipe</button>
  </div>`);
  const box = $("[data-items]", root), sum = $("[data-sum]", root);
  const foodsById = new Map();
  items.forEach((it) => it.matches.forEach((m) => foodsById.set(String(m.id), m)));

  const calc = () => {
    const t = { kcal: 0, protein: 0, carbs: 0, fat: 0 };
    let raw = 0, missing = 0;
    for (const it of items) {
      if (it.choice === "skip") continue;
      const f = foodsById.get(it.choice);
      if (!f || !it.grams) { missing++; continue; }
      raw += it.grams;
      for (const k in t) t[k] += ((f[k] || 0) * it.grams) / 100;
    }
    const weight = parseFloat($("[data-final]", root).value) || raw;
    const serv = parseFloat($("[data-servings]", root).value) || 1;
    sum.innerHTML = `<div class="muted small">Whole dish</div>
      <div class="kpg num">${weight ? (t.kcal / weight).toFixed(2) : "–"} <span style="font-size:18px;font-weight:600">kcal per gram</span></div>
      <dl><dt>Total energy</dt><dd>${fmt(t.kcal)} kcal</dd>
        <dt>Per serving (1/${r1(serv)})</dt><dd>${fmt(weight / serv)} g · ${fmt(t.kcal / serv)} kcal</dd>
        ${d.nutrition?.kcal ? `<dt>Mealie says per serving</dt><dd>${fmt(d.nutrition.kcal)} kcal</dd>` : ""}
      </dl>
      ${missing ? `<p class="small" style="color:var(--over);margin:8px 0 0">${missing} ingredient${missing > 1 ? "s" : ""} still need${missing > 1 ? "" : "s"} a food and grams, or Skip.</p>` : ""}`;
  };

  items.forEach((it, i) => {
    const row = el(`<div class="ai-item">
      <div class="small muted" style="margin-bottom:6px">${esc(it.line)}</div>
      <div class="row">
        <select data-food aria-label="Food for ${esc(it.name)}"></select>
        <input data-grams class="g" type="number" inputmode="decimal" min="0" step="any" value="${it.grams ?? ""}" placeholder="g" aria-label="Grams" style="flex:0 0 92px">
        <span class="muted small" style="flex:0">g</span>
      </div></div>`);
    const sel = $("[data-food]", row), grams = $("[data-grams]", row);
    const fill = () => {
      sel.innerHTML = `${it.choice ? "" : '<option value="" selected>Choose a food…</option>'}
        ${it.matches.map((m) => `<option value="${m.id}" ${String(m.id) === it.choice ? "selected" : ""}>${esc(m.name)} · ${fmt(m.kcal)} kcal/100 g</option>`).join("")}
        <option value="search">Search for another food…</option>
        <option value="skip" ${it.choice === "skip" ? "selected" : ""}>Skip (salt, water…)</option>`;
      row.style.opacity = it.choice === "skip" ? 0.55 : 1;
      grams.disabled = it.choice === "skip";
      const bad = it.choice !== "skip" && (!it.choice || !it.grams);
      row.style.outline = bad ? "2px solid color-mix(in srgb, var(--over) 45%, transparent)" : "";
    };
    fill();
    sel.onchange = () => {
      if (sel.value === "search") {
        openAdd({ mode: "recipe", onPick: ({ food, grams: g }) => {
          foodsById.set(String(food.id), food);
          if (!it.matches.some((m) => m.id === food.id)) it.matches.unshift(food);
          it.choice = String(food.id); it.grams = g; grams.value = g; fill(); calc();
        } });
        sel.value = it.choice || "";
        return;
      }
      it.choice = sel.value; fill(); calc();
    };
    grams.oninput = () => { it.grams = parseFloat(grams.value) || null; fill(); calc(); };
    box.append(row);
  });
  $("[data-final]", root).oninput = calc;
  $("[data-servings]", root).oninput = calc;
  calc();

  $("[data-save]", root).onclick = async () => {
    const chosen = items.filter((it) => it.choice && it.choice !== "skip" && it.grams > 0);
    if (!chosen.length) return toast("Choose at least one ingredient", true);
    const open = items.filter((it) => it.choice !== "skip" && !(it.choice && it.grams > 0)).length;
    if (open && !confirm(`${open} ingredient${open > 1 ? "s are" : " is"} left out. Create the recipe anyway?`)) return;
    try {
      const saved = await api("/api/recipes", { method: "POST", body: {
        name: $("[data-name]", root).value, servings: $("[data-servings]", root).value,
        final_weight_g: $("[data-final]", root).value || null,
        notes: d.source_url ? `From ${d.source_url}` : "",
        source_url: d.source_url || null, mealie_id: d.mealie_id || null, mealie_slug: d.mealie_slug || null,
        items: chosen.map((it) => ({ food_id: +it.choice, grams: it.grams })),
      } });
      state.importDraft = null;
      toast("Recipe created");
      location.hash = `#/recipe/${saved.id}`;
    } catch (e) { fail(e); }
  };
  view.replaceChildren(root);
}

async function renderRecipe(id) {
  const r = id === "new"
    ? { id: null, name: "", servings: 4, final_weight_g: null, notes: "", items: [] }
    : await api(`/api/recipes/${id}`);
  const items = r.items.map((i) => ({ food: i.food, grams: i.grams }));
  const root = el(`<div>
    <div class="topbar"><a class="icon-btn" href="#/recipes" aria-label="All recipes">${ICON.left}</a>
      <div style="flex:1"></div>${r.id ? '<button class="btn danger" style="flex:0" data-del>Delete</button>' : ""}</div>
    <label class="field"><span>Recipe name</span><input data-name value="${esc(r.name)}" placeholder="e.g. Chili con carne" style="font-size:20px;font-weight:650"></label>
    <h2 style="margin:18px 0 8px">Ingredients</h2>
    <div class="list" data-items></div>
    <button class="btn ghost block" style="margin-top:10px" data-add>${ICON.plus} Add ingredient</button>
    <div class="grid2" style="margin-top:12px">
      <label class="field"><span>Cooked weight (g)</span><input data-final type="number" inputmode="decimal" min="1" step="any" value="${r.final_weight_g ?? ""}" placeholder="optional"></label>
      <label class="field"><span>Servings</span><input data-servings type="number" inputmode="decimal" min="0.1" step="any" value="${r.servings}"></label>
    </div>
    <p class="hint">Weigh the finished dish without the pot. Cooking adds or boils off water, so this is what makes kcal per gram accurate. Left empty, the raw ingredient weight is used.</p>
    <div class="recipe-sum" data-sum aria-live="polite"></div>
    <label class="field"><span>Notes</span><textarea data-notes rows="3" placeholder="Method, pot weight, tweaks…">${esc(r.notes || "")}</textarea></label>
    <button class="btn block" data-save>${r.id ? "Save recipe" : "Create recipe"}</button>
    ${r.food_id ? '<button class="btn ghost block" style="margin-top:10px" data-log>Log a portion</button>' : ""}
  </div>`);

  const list = $("[data-items]", root), sum = $("[data-sum]", root);
  const finalIn = $("[data-final]", root), servIn = $("[data-servings]", root);
  const draw = () => {
    list.replaceChildren();
    if (!items.length) list.append(el('<div class="empty" style="padding:14px 16px">Add what goes into the dish, weighed raw.</div>'));
    items.forEach((it, i) => {
      const row = el(`<button class="item"><div class="main"><div class="title">${esc(it.food.name)}</div>
        <div class="meta num">${r0(it.grams)} g · ${fmt(it.food.kcal)} kcal/100 g</div></div>
        <div class="kcal num">${fmt((it.food.kcal * it.grams) / 100)}</div></button>`);
      row.onclick = () => {
        const sheet = openSheet();
        amountPanel(sheet, it.food, {
          title: it.food.name, grams: it.grams, action: "Update amount",
          extra: (box) => {
            const del = el('<button type="button" class="btn danger block" style="margin-top:8px">Remove ingredient</button>');
            del.onclick = () => { items.splice(i, 1); sheet.close(); draw(); };
            box.append(del);
          },
          onDone: async (g) => { it.grams = g; sheet.close(); draw(); },
        });
      };
      list.append(row);
    });
    calc();
  };
  const calc = () => {
    const t = { kcal: 0, protein: 0, carbs: 0, fat: 0 };
    let raw = 0;
    for (const it of items) {
      raw += it.grams;
      for (const k in t) t[k] += ((it.food[k] || 0) * it.grams) / 100;
    }
    const weight = parseFloat(finalIn.value) || raw;
    const serv = parseFloat(servIn.value) || 1;
    const per = (k) => (weight ? (t[k] / weight) * 100 : 0);
    sum.innerHTML = `<div class="muted small">Whole dish</div>
      <div class="kpg num">${weight ? (t.kcal / weight).toFixed(2) : "–"} <span style="font-size:18px;font-weight:600">kcal per gram</span></div>
      <dl>
        <dt>Total energy</dt><dd>${fmt(t.kcal)} kcal</dd>
        <dt>Total weight${finalIn.value ? " (cooked)" : " (raw)"}</dt><dd>${fmt(weight)} g</dd>
        <dt>Per 100 g</dt><dd>${fmt(per("kcal"))} kcal · P ${r1(per("protein"))} · C ${r1(per("carbs"))} · F ${r1(per("fat"))}</dd>
        <dt>One serving (1/${r1(serv)})</dt><dd>${fmt(weight / serv)} g · ${fmt(t.kcal / serv)} kcal</dd>
        ${finalIn.value && raw ? `<dt>Weight change from cooking</dt><dd>${weight >= raw ? "+" : "−"}${Math.abs(Math.round(((weight - raw) / raw) * 100))} %</dd>` : ""}
      </dl>`;
  };
  finalIn.oninput = calc;
  servIn.oninput = calc;
  draw();

  $("[data-add]", root).onclick = () =>
    openAdd({ mode: "recipe", onPick: ({ food, grams }) => { items.push({ food, grams }); draw(); } });
  $("[data-save]", root).onclick = async () => {
    const body = {
      name: $("[data-name]", root).value, servings: servIn.value, final_weight_g: finalIn.value || null,
      notes: $("[data-notes]", root).value, items: items.map((i) => ({ food_id: i.food.id, grams: i.grams })),
    };
    try {
      const saved = await api(r.id ? `/api/recipes/${r.id}` : "/api/recipes", { method: r.id ? "PUT" : "POST", body });
      toast(r.id ? "Recipe saved" : "Recipe created");
      if (!r.id) location.hash = `#/recipe/${saved.id}`;
      else renderRecipe(saved.id);
    } catch (e) { fail(e); }
  };
  $("[data-del]", root)?.addEventListener("click", async () => {
    if (!confirm(`Delete “${r.name}”? Days you already logged it keep their numbers.`)) return;
    try { await api(`/api/recipes/${r.id}`, { method: "DELETE" }); toast("Recipe deleted"); location.hash = "#/recipes"; }
    catch (e) { fail(e); }
  });
  $("[data-log]", root)?.addEventListener("click", async () => {
    const food = await api(`/api/foods/${r.food_id}`);
    const sheet = openSheet();
    amountForAdd(sheet, { mode: "diary", date: todayISO(), meal: defaultMeal(), onDone: () => {} }, food);
  });
  view.replaceChildren(root);
}

// ---------------------------------------------------------------- meal plan

async function renderPlan() {
  state.planStart = state.planStart || mondayOf(todayISO());
  const start = state.planStart;
  const plan = await api(`/api/plan?start=${start}&days=7`);
  const root = el(`<div>
    <div class="topbar">
      <h1>Meal plan</h1>
      <div class="datepager">
        <button class="icon-btn" data-week="-7" aria-label="Previous week">${ICON.left}</button>
        <button class="btn plain" data-thisweek>${start === mondayOf(todayISO()) ? "This week" : esc(fmtDay(start, false))}</button>
        <button class="icon-btn" data-week="7" aria-label="Next week">${ICON.right}</button>
      </div>
    </div>
    <p class="muted" style="margin-top:0">Shared with the household. Amounts are per person; each of you logs your own portion.</p>
    ${plan.mealie ? `<div class="row" style="justify-content:space-between;margin:-4px 0 6px"><span class="small muted">Synced with Mealie</span>
      <button class="btn plain" style="flex:0" data-msync>Sync now</button></div>` : ""}
    <div data-days></div></div>`);
  const daysEl = $("[data-days]", root);
  for (const [date, meals] of Object.entries(plan.days)) {
    const all = MEALS.flatMap((m) => meals[m]);
    const kcal = all.reduce((s, i) => s + i.kcal, 0);
    const day = el(`<section class="day">
      <div class="day-head${date === todayISO() ? " today" : ""}">
        <h3>${esc(fmtDay(date, false))}${date === todayISO() ? " · today" : ""}</h3>
        <span class="muted small num">${all.length ? fmt(kcal) + " kcal" : ""}</span></div>
      <div class="list"></div></section>`);
    const list = $(".list", day);
    for (const m of MEALS) {
      if (!meals[m].length) continue;
      list.append(el(`<div class="plan-meal">${MEAL_LABEL[m]}</div>`));
      for (const it of meals[m]) {
        const row = el(`<button class="item"><div class="main"><div class="title">${esc(it.food.name)}</div>
          <div class="meta num">${it.origin === "mealie" ? '<span class="src">Mealie</span>' : ""}${r0(it.grams)} g${it.added_by ? " · added by " + esc(it.added_by) : ""}${it.note ? " · " + esc(it.note) : ""}</div></div>
          <div class="kcal num">${fmt(it.kcal)}</div></button>`);
        row.onclick = () => planItemSheet(it, date);
        list.append(row);
      }
    }
    const actions = el(`<div class="day-actions"><button class="btn plain">${ICON.plus} Add</button>
      ${all.length ? '<button class="btn plain" data-logday>Log to my diary</button>' : ""}</div>`);
    $("button", actions).onclick = () => openAdd({ mode: "plan", date, meal: "dinner", onDone: renderPlan });
    $("[data-logday]", actions)?.addEventListener("click", async () => {
      try {
        const r = await api("/api/plan/log", { method: "POST", body: { date } });
        toast(`Logged ${r.logged} item${r.logged === 1 ? "" : "s"} to ${fmtDay(date).toLowerCase()}`);
      } catch (e) { fail(e); }
    });
    list.append(actions);
    daysEl.append(day);
  }
  $("[data-msync]", root)?.addEventListener("click", async (e) => {
    e.target.disabled = true;
    try {
      const st = await api("/api/mealie/sync", { method: "POST" });
      toast(`Synced: ${st.pulled} from Mealie, ${st.pushed} to Mealie${st.removed ? `, ${st.removed} removed` : ""}`);
      renderPlan();
    } catch (err) { fail(err); e.target.disabled = false; }
  });
  $$("[data-week]", root).forEach((b) => (b.onclick = () => { state.planStart = addDays(start, +b.dataset.week); renderPlan(); }));
  $("[data-thisweek]", root).onclick = () => { state.planStart = mondayOf(todayISO()); renderPlan(); };
  view.replaceChildren(root);
}

function planItemSheet(it, date) {
  const sheet = openSheet();
  amountPanel(sheet, it.food, {
    title: it.food.name, grams: it.grams, meal: it.meal || "dinner", action: "Log my portion",
    extra: (box) => {
      const del = el('<button type="button" class="btn danger block" style="margin-top:8px">Remove from plan</button>');
      del.onclick = async () => {
        try { await api(`/api/plan/${it.id}`, { method: "DELETE" }); sheet.close(); toast("Removed from plan"); renderPlan(); }
        catch (e) { fail(e); }
      };
      box.append(del);
    },
    onDone: async (grams) => {
      await api("/api/plan/log", { method: "POST", body: { ids: [it.id], grams: { [it.id]: grams } } });
      sheet.close();
      toast(`Logged to ${fmtDay(date).toLowerCase()}`);
    },
  });
}

// ---------------------------------------------------------------- settings ("You")

async function renderSettings() {
  await loadSettings();
  const s = state.settings, u = state.user;
  const root = el(`<div>
    <h1>${esc(u.username)}</h1>
    <form class="section" data-goals>
      <h2>Daily goals</h2>
      <div class="grid2">
        <label class="field"><span>Energy (kcal)</span><input name="kcal_goal" type="number" inputmode="numeric" min="0" value="${r0(u.kcal_goal)}"></label>
        <label class="field"><span>Protein (g)</span><input name="protein_goal" type="number" inputmode="numeric" min="0" value="${r0(u.protein_goal)}"></label>
        <label class="field"><span>Carbohydrates (g)</span><input name="carbs_goal" type="number" inputmode="numeric" min="0" value="${r0(u.carbs_goal)}"></label>
        <label class="field"><span>Fat (g)</span><input name="fat_goal" type="number" inputmode="numeric" min="0" value="${r0(u.fat_goal)}"></label>
      </div>
      <button class="btn" type="submit">Save goals</button>
    </form>
    <div data-admin></div>
    <section class="section">
      <h2>Food databases</h2>
      <p class="small" data-slv></p>
      <p class="small muted">Barcodes are looked up in Open Food Facts (ODbL) and saved here once found. Swedish food data © Livsmedelsverket (CC BY 4.0). USDA FoodData Central is public domain.</p>
    </section>
    <section class="section">
      <h2>Your data</h2>
      <p class="small muted">Everything you've logged, as a spreadsheet-friendly file.</p>
      <button class="btn ghost" type="button" data-export>Download diary (CSV)</button>
    </section>
    ${HA_MODE ? `<section class="section"><h2>Account</h2><p class="small muted">You're signed in through Home Assistant as ${esc(u.username)}. Everyone with a Home Assistant login has their own diary and goals here.</p></section>` : ""}
    <form class="section${HA_MODE ? " hidden" : ""}" data-pw>
      <h2>Change password</h2>
      <label class="field"><span>Current password</span><input name="password" type="password" autocomplete="current-password" required></label>
      <label class="field"><span>New password</span><input name="new_password" type="password" autocomplete="new-password" minlength="6" required></label>
      <button class="btn" type="submit">Change password</button>
    </form>
    ${NATIVE ? `<section class="section" data-native-settings>
      <h2>iPhone app</h2>
      <label class="row hidden" style="justify-content:space-between;margin:12px 0" data-health-row>
        <span>Save to Apple Health<br><span class="small muted">Your daily calories, protein, carbs, fat and fibre</span></span>
        <input type="checkbox" data-health style="flex:0;width:26px;min-height:26px">
      </label>
      <p class="small muted">Connected to ${esc(location.host)}.</p>
      <button class="btn ghost" data-change-server>Change server</button>
    </section>` : ""}
    ${HA_MODE ? "" : '<button class="btn danger block" data-logout>Sign out</button>'}
  </div>`);

  $("[data-goals]", root).onsubmit = async (e) => {
    e.preventDefault();
    try { state.user = (await api("/api/me", { method: "PUT", body: Object.fromEntries(new FormData(e.target)) })).user; toast("Goals saved"); }
    catch (err) { fail(err); }
  };
  $("[data-pw]", root).onsubmit = async (e) => {
    e.preventDefault();
    try { await api("/api/me", { method: "PUT", body: Object.fromEntries(new FormData(e.target)) }); e.target.reset(); toast("Password changed"); }
    catch (err) { fail(err); }
  };
  const healthBox = $("[data-health]", root);
  if (healthBox) {
    native("healthAvailable").then((r) => { if (r?.available) $("[data-health-row]", root).classList.remove("hidden"); }).catch(() => {});
    healthBox.checked = healthEnabled();
    healthBox.onchange = async () => {
      if (healthBox.checked) {
        healthBox.disabled = true;
        try { await enableHealth(); toast("Saving to Apple Health"); }
        catch (e) { healthBox.checked = false; fail(e); }
        finally { healthBox.disabled = false; }
      } else {
        try { localStorage.removeItem(healthKey()); } catch { /* ignore */ }
        toast("Stopped saving to Apple Health. What's already there stays.");
      }
    };
    $("[data-change-server]", root).onclick = () => { location.href = "capacitor://localhost/index.html?setup=1"; };
  }
  $("[data-export]", root).onclick = async () => {
    try {
      const res = HA_MODE ? await haRequest("/api/export.csv", { raw: true }) : null;
      const text = HA_MODE ? res.text : await (await fetch("/api/export.csv", { credentials: "same-origin" })).text();
      const a = el(`<a download="local-tracker-${esc(u.username)}.csv"></a>`);
      a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
      document.body.append(a); a.click(); a.remove();
    } catch (e) { fail(e); }
  };
  $("[data-logout]", root)?.addEventListener("click", async () => { await api("/api/auth/logout", { method: "POST" }); state.user = null; renderAuth(false); });

  const slvEl = $("[data-slv]", root);
  const drawSlv = (st) => {
    const msg = st.state === "running"
      ? `Downloading Livsmedelsverket's food database… ${st.done} of ${st.total || "?"} foods.`
      : st.state === "error" ? `The Livsmedelsverket download stopped: ${st.error}`
      : st.count ? `${fmt(st.count)} Swedish foods from Livsmedelsverket${st.imported ? `, downloaded ${st.imported}` : ""}.`
      : "Livsmedelsverket's food database hasn't been downloaded yet.";
    slvEl.innerHTML = esc(msg) + (u.is_admin && st.state !== "running" ? ' <button class="btn plain" data-slvgo>Download now</button>' : "");
    $("[data-slvgo]", slvEl)?.addEventListener("click", async () => {
      try { await api("/api/settings/slv-import", { method: "POST" }); poll(); } catch (e) { fail(e); }
    });
  };
  const poll = async () => {
    const st = (await api("/api/settings")).slv;
    if (!document.body.contains(slvEl)) return;
    drawSlv(st);
    if (st.state === "running") setTimeout(poll, 2000);
  };
  drawSlv(s.slv);
  if (s.slv.state === "running") setTimeout(poll, 2000);

  if (u.is_admin) await adminSections($("[data-admin]", root), s);
  else $("[data-admin]", root).append(el(`<section class="section"><h2>Photo recognition</h2><p class="small">${s.photo_providers.length
    ? "On, using " + s.photo_providers.map((p) => PROVIDER_LABEL[p]).join(" and ") + "."
    : "Not set up. The household admin can turn it on."}</p></section>`));
  view.replaceChildren(root);
}

async function adminSections(box, s) {
  const users = await api("/api/users");
  const a = s.ai;
  const hh = el(`<section class="section">
    <h2>Household</h2>
    <div class="list" style="margin:8px -16px 0;border-radius:0" data-users></div>
    <form class="row" style="margin-top:12px;flex-wrap:wrap" data-adduser>
      <input name="username" placeholder="Name" required autocapitalize="none" style="flex:1 1 120px">
      <input name="password" type="password" placeholder="Password" required minlength="6" autocomplete="new-password" style="flex:1 1 120px">
      <button class="btn" type="submit" style="flex:0 0 auto">Add person</button>
    </form>
    <p class="hint">Everyone shares recipes, foods and the meal plan. Diaries and goals are personal.</p>
  </section>`);
  const ul = $("[data-users]", hh);
  for (const usr of users) {
    const row = el(`<div class="item" style="cursor:default"><div class="main"><div class="title">${esc(usr.username)}</div>
      <div class="meta">${usr.is_admin ? "Admin" : "Member"}</div></div>
      ${usr.id === state.user.id ? "" : '<button class="btn plain" data-reset>Reset password</button><button class="btn danger" data-del>Remove</button>'}</div>`);
    $("[data-reset]", row)?.addEventListener("click", async () => {
      const pw = prompt(`New password for ${usr.username} (at least 6 characters)`);
      if (!pw) return;
      try { await api(`/api/users/${usr.id}/password`, { method: "PUT", body: { password: pw } }); toast("Password reset"); } catch (e) { fail(e); }
    });
    $("[data-del]", row)?.addEventListener("click", async () => {
      if (!confirm(`Remove ${usr.username} and their diary?`)) return;
      try { await api(`/api/users/${usr.id}`, { method: "DELETE" }); renderSettings(); } catch (e) { fail(e); }
    });
    ul.append(row);
  }
  $("[data-adduser]", hh).onsubmit = async (e) => {
    e.preventDefault();
    try { await api("/api/users", { method: "POST", body: Object.fromEntries(new FormData(e.target)) }); toast("Added"); renderSettings(); }
    catch (err) { fail(err); }
  };

  const v = (k) => esc(a[k] || "");
  const ai = el(`<form class="section">
    <h2>Photo recognition</h2>
    <p class="small muted">Set up one or both. With both, people pick which to use when they take a photo.</p>
    <label class="field"><span>Default</span><select name="ai_provider">${["ollama", "anthropic", "openai"].map((p) =>
      `<option value="${p}" ${a.ai_provider === p ? "selected" : ""}>${PROVIDER_LABEL[p]}</option>`).join("")}</select></label>
    <h3 style="margin-top:16px">Ollama, on your own hardware</h3>
    <label class="field"><span>Server address</span><input name="ollama_url" value="${v("ollama_url")}" placeholder="http://ollama:11434" autocapitalize="none"></label>
    <label class="field"><span>Vision model</span><div class="row"><input name="ollama_model" value="${v("ollama_model")}" list="ollama-models" autocapitalize="none">
      <button type="button" class="btn ghost" style="flex:0" data-models>List models</button></div></label>
    <datalist id="ollama-models"></datalist>
    <p class="hint">Needs a model that understands images, such as qwen2.5vl:7b, llama3.2-vision or gemma3. Leave the address empty to turn Ollama off.</p>
    <h3 style="margin-top:16px">Cloud API</h3>
    <p class="hint">Photos are sent to the provider for each estimate.</p>
    <div class="grid2">
      <label class="field"><span>Claude API key</span><input name="anthropic_api_key" value="${v("anthropic_api_key")}" autocomplete="off" placeholder="sk-ant-…"></label>
      <label class="field"><span>Claude model</span><input name="anthropic_model" value="${v("anthropic_model")}" autocapitalize="none"></label>
      <label class="field"><span>OpenAI API key</span><input name="openai_api_key" value="${v("openai_api_key")}" autocomplete="off" placeholder="sk-…"></label>
      <label class="field"><span>OpenAI model</span><input name="openai_model" value="${v("openai_model")}" autocapitalize="none"></label>
    </div>
    <label class="field"><span>OpenAI-compatible base URL</span><input name="openai_base_url" value="${v("openai_base_url")}" autocapitalize="none"></label>
    <h3 style="margin-top:16px">USDA</h3>
    <label class="field"><span>FoodData Central API key</span><input name="usda_api_key" value="${esc(s.usda_api_key)}" autocomplete="off" placeholder="DEMO_KEY is used when empty"></label>
    <p class="hint">The shared demo key allows about 30 searches an hour. A free personal key from fdc.nal.usda.gov/api-key-signup allows 1,000.</p>
    <button class="btn" type="submit">Save settings</button>
  </form>`);
  ai.onsubmit = async (e) => {
    e.preventDefault();
    try {
      state.settings = await api("/api/settings", { method: "PUT", body: Object.fromEntries(new FormData(ai)) });
      toast(state.settings.photo_providers.length ? `Photo recognition: ${state.settings.photo_providers.map((p) => PROVIDER_LABEL[p]).join(" and ")}` : "Settings saved");
    } catch (err) { fail(err); }
  };
  $("[data-models]", ai).onclick = async () => {
    const url = $('[name="ollama_url"]', ai).value.trim();
    if (!url) return toast("Enter the Ollama address first", true);
    try {
      const models = await api(`/api/settings/ollama-models?url=${encodeURIComponent(url)}`);
      $("#ollama-models", ai).replaceChildren(...models.map((m) => el(`<option value="${esc(m)}"></option>`)));
      toast(models.length ? `Found ${models.length} model${models.length > 1 ? "s" : ""}: ${models.slice(0, 3).join(", ")}${models.length > 3 ? "…" : ""}` : "Ollama is reachable but has no models. Run: ollama pull qwen2.5vl:7b");
    } catch (err) { fail(err); }
  };
  const m = s.mealie || {};
  const ms = m.status || {};
  const mealieForm = el(`<form class="section">
    <h2>Mealie</h2>
    <p class="small muted">Import recipes from Mealie and keep the meal plan in sync both ways. In Mealie, create a token under your user → API Tokens.</p>
    <label class="field"><span>Mealie address</span><input name="mealie_url" value="${esc(m.url || "")}" placeholder="http://192.168.1.20:9000" autocapitalize="none"></label>
    <label class="field"><span>API token</span><input name="mealie_token" value="${esc(m.token || "")}" autocomplete="off"></label>
    <label class="row" style="margin:12px 0;justify-content:flex-start;gap:10px"><input type="checkbox" name="mealie_sync" ${m.sync !== false ? "checked" : ""} style="flex:0;width:22px;min-height:22px">
      <span>Sync the meal plan with Mealie</span></label>
    <p class="small muted">${ms.last ? `Last synced ${esc(ms.last)}.` : ""} ${ms.error ? `<span style="color:var(--over)">${esc(ms.error)}</span>` : ""}</p>
    <div class="row" style="flex-wrap:wrap;gap:8px">
      <button class="btn" type="submit" style="flex:0">Save</button>
      <button class="btn ghost" type="button" data-mcheck style="flex:0">Test connection</button>
      <button class="btn ghost" type="button" data-msync style="flex:0">Sync now</button></div>
  </form>`);
  mealieForm.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(mealieForm);
    try {
      state.settings = await api("/api/settings", { method: "PUT", body: {
        mealie_url: fd.get("mealie_url"), mealie_token: fd.get("mealie_token"), mealie_sync: !!fd.get("mealie_sync") } });
      toast(state.settings.mealie.configured ? "Mealie connected" : "Saved");
    } catch (err) { fail(err); }
  };
  $("[data-mcheck]", mealieForm).onclick = async () => {
    try { const r = await api("/api/mealie/check"); toast(`Connected to Mealie ${r.version}`); } catch (err) { fail(err); }
  };
  $("[data-msync]", mealieForm).onclick = async () => {
    try { const st = await api("/api/mealie/sync", { method: "POST" }); toast(`Synced: ${st.pulled} from Mealie, ${st.pushed} to Mealie`); }
    catch (err) { fail(err); }
  };
  box.append(...(HA_MODE ? [] : [hh]), ai, mealieForm);
}

// ---------------------------------------------------------------- routing

async function route() {
  if (!state.user) return;
  $("#tabs").classList.remove("hidden");
  const hash = location.hash.replace(/^#\/?/, "");
  const [page, arg] = hash.split("/");
  const tab = { "": "today", plan: "plan", recipes: "recipes", recipe: "recipes", settings: "settings" }[page] || "today";
  $$("#tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === tab));
  try {
    if (page === "plan") await renderPlan();
    else if (page === "recipes") await renderRecipes();
    else if (page === "recipe" && arg === "import") renderImportReview();
    else if (page === "recipe") await renderRecipe(arg || "new");
    else if (page === "settings") await renderSettings();
    else await renderToday();
  } catch (e) { fail(e); }
}

$("#fab").onclick = () => {
  const hash = location.hash;
  if (hash.startsWith("#/plan")) openAdd({ mode: "plan", date: todayISO(), meal: "dinner", onDone: renderPlan });
  else openAdd({ mode: "diary", date: hash === "" || hash === "#/" ? state.date : todayISO() });
};
window.addEventListener("hashchange", route);

(async function boot() {
  if (HA_MODE) {
    document.documentElement.classList.add("in-ha");
    await hassPromise;
  } else if ("serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  try {
    const st = await api("/api/auth");
    if (!st.user) return renderAuth(st.needs_setup);
    state.user = st.user;
    await loadSettings();
    route();
  } catch (e) {
    view.replaceChildren(el(`<div class="auth"><h1>Can't reach the server</h1><p class="muted">${esc(e.message)}</p>
      <button class="btn" onclick="location.reload()">Try again</button></div>`));
  }
})();
