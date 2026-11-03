"use strict";
// Bladesmith page. All game work happens in Python (window.pywebview.api); this file only renders state.

const FAMILIES = [["all", "All"], ["one-handed", "One-handed"], ["two-handed", "Two-handed"], ["dual", "Dual"], ["chakram", "Other"]];
const ORIGINAL = "";
const S = { data: null, base: null, skin: null, browsing: false, family: "all", query: "", recipe: [] };
const $ = (id) => document.getElementById(id);
const ICONS = {
  undo: '<path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/>',
  arrow: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  warn: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
};
function icon(name) {
  const span = document.createElement("span");
  span.innerHTML = `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
  return span.firstChild;
}
const byKey = (k) => S.data.weapons.find((w) => w.key === k);
// the builder only keeps a scabbard that sits where the base weapon already has one (moving it crashes the game)
const scabFits = (base, skin) => skin.scabbard && base.scab_sockets.slice(0, Math.min(base.blades, skin.blades))
  .some((s, i) => s && s === skin.scab_sockets[Math.min(i, skin.blades - 1)]);

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c != null) e.append(c);
  return e;
}

function toast(msg, err = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "show" + (err ? " err" : "");
  clearTimeout(toast.h);
  toast.h = setTimeout(() => (t.className = ""), 3800);
}

window.onLog = (line) => {
  const log = $("log");
  log.textContent += line + "\n";
  log.scrollTop = log.scrollHeight;
  const splash = $("loading-log");  // gone once the page is ready
  if (splash) splash.textContent = line;
};

// ---------- cards ----------
function picture(w, cls = "") {
  return w && w.img ? el("img", { src: w.img, alt: "", class: cls }) : el("div", { class: "noimg" }, "no picture");
}

function card(w, selected, onclick) {
  const tags = [el("span", { class: "tag" }, w.kind)];
  if (w.fades) tags.push(el("span", { class: "tag fade", title: "ends its trails with a fade" }, "fade"));
  if (w.tested) tags.push(el("span", { class: "tag tested", title: "checked in the game" }, "tested"));
  return el("button", { type: "button", class: `card${selected ? " sel" : ""}`, onclick, title: w.key, "aria-pressed": String(!!selected) },
    el("div", { class: "img" }, picture(w)),
    el("div", { class: `name${w.named ? "" : " key"}` }, w.name),
    el("div", { class: "tags" }, tags));
}

function renderFilters() {
  const box = $("base-filters");
  box.replaceChildren(...FAMILIES.map(([f, label]) =>
    el("button", { type: "button", class: `chip${S.family === f ? " on" : ""}`, "aria-pressed": String(S.family === f),
      onclick: () => { S.family = f; renderFilters(); renderBases(); } }, label)));
}

function matches(w) {
  const q = S.query.trim().toLowerCase();
  const famOk = S.family === "all" || w.family === S.family || (S.family === "chakram" && !["one-handed", "two-handed", "dual"].includes(w.family));
  return famOk && (!q || w.name.toLowerCase().includes(q) || w.key.toLowerCase().includes(q));
}

function renderBases() {
  // once a base is picked the grid folds into one row, so the look grid sits right below it
  const folded = S.base && !S.browsing;
  $("base-filters").hidden = $("base-search").hidden = folded;
  if (folded) {
    const w = byKey(S.base);
    $("base-grid").replaceChildren(card(w, true, () => {}),
      el("div", { class: "change" }, el("button", { class: "ghost", onclick: () => { S.browsing = true; renderBases(); } }, "Change base")));
    return;
  }
  const list = S.data.weapons.filter(matches).sort((a, b) => (b.named - a.named) || a.name.localeCompare(b.name));
  $("base-grid").replaceChildren(...list.map((w) => card(w, S.base === w.key, () => selectBase(w.key))));
}

function renderSkins() {
  const base = byKey(S.base);
  $("any-type").closest(".toggle").hidden = !base.skinnable;
  if (!base.skinnable) {
    $("skin-grid").replaceChildren(el("div", { class: "locked" },
      `${base.name} keeps its blade in a different kind of asset, so it can't wear another look yet. You can still change its trails and their color on the right.`));
    return;
  }
  const any = $("any-type").checked;
  const keep = el("button", { type: "button", class: `card keep${S.skin === null ? " sel" : ""}`, onclick: () => selectSkin(null), "aria-pressed": String(S.skin === null) },
    el("div", { class: "img" }, icon("undo")), el("div", { class: "name" }, "Keep its own look"), el("div", { class: "tags" }));
  const skins = S.data.weapons
    .filter((w) => w.key !== base.key && w.skinnable && (any || w.family === base.family))
    .sort((a, b) => (b.named - a.named) || a.name.localeCompare(b.name));
  $("skin-grid").replaceChildren(keep, ...skins.map((w) => card(w, S.skin === w.key, () => selectSkin(w.key))));
}

// ---------- preview ----------
function renderPreview() {
  const base = byKey(S.base);
  $("preview-empty").hidden = !!base;
  $("preview-body").hidden = !base;
  if (!base) return;
  const skin = S.skin ? byKey(S.skin) : null;
  $("pv-arrow").replaceChildren(icon("arrow"));
  $("pv-base-img").replaceChildren(picture(base));
  $("pv-base-name").textContent = base.name;
  $("pv-skin-img").replaceChildren(picture(skin || base));
  $("pv-skin-name").textContent = skin ? skin.name : base.name + " (unchanged)";

  const notes = [];
  if (skin && skin.family !== base.family)
    notes.push(el("div", { class: "warn" }, icon("warn"), ` ${skin.kind} look on a ${base.kind} weapon: hitboxes and animations stay with the base, the blade may not line up.`));
  if (skin && skin.blades !== base.blades)
    notes.push(el("div", { class: "warn" }, icon("warn"), ` ${base.name} has ${base.blades} blade(s), ${skin.name} has ${skin.blades}. Only matching slots change.`));
  if (base.fades)
    notes.push(el("div", {}, `${base.name} ends its trails with a fade. Pick effects marked fade: the others keep following the blade while you run.`));
  notes.push(el("div", {}, "Stats, perks, moveset and hitboxes always stay with the base weapon."));
  $("pv-notes").replaceChildren(...notes);

  const scab = $("scabbard");
  const hasScab = !!(skin && scabFits(base, skin));
  scab.closest(".toggle").classList.toggle("off", !hasScab);
  if (!hasScab) scab.checked = false;

  const covered = S.data.presets.filter((p) => base.trails.some((t) => p.systems.includes(t.name.toLowerCase())));
  $("color").replaceChildren(el("option", { value: "" }, "original"),
    covered.length ? el("optgroup", { label: "Made for this weapon" }, covered.map((p) => el("option", { value: "preset:" + p.id }, p.id))) : null,
    el("optgroup", { label: "Tint (experimental)" }, S.data.tints.map((t) => el("option", { value: "tint:" + t.id }, t.id))));
  $("color-hint").textContent = "";
  S.trailChoice = {};
  renderTrailRows();
  S.bladeFrom = null;
  renderBlade();
}

// ---------- blade color ----------
const hex = (rgb) => "#" + rgb.map((v) => Math.round(Math.min(1, Math.max(0, v)) * 255).toString(16).padStart(2, "0")).join("");
const gray = (rgb, k) => hex(Array(3).fill(Math.max(...rgb) * k));

async function renderBlade() {
  const look = byKey(S.skin || S.base);
  const box = $("blade-from");
  $("blade-opt").hidden = !look.skinnable;
  if (!look.skinnable) return;
  S.palettes = S.palettes || {};
  if (!S.palettes[look.key]) {
    box.replaceChildren(el("span", { class: "muted" }, "Reading the blade's colors..."));
    $("blade-to").hidden = true;
    const res = await window.pywebview.api.blade_palette(look.key);
    if (look.key !== (S.skin || S.base)) return;  // the pick changed while reading
    S.palettes[look.key] = res.ok ? res.colors : [];
    if (!res.ok) $("blade-hint").textContent = "Can't read this look's colors: " + res.error;
  }
  const colors = S.palettes[look.key];
  const pick = (hue) => { S.bladeFrom = hue; renderBlade(); };
  const sw = (on, label, color, onclick, title) => el("button", { type: "button", class: `swatch${on ? " on" : ""}`,
    "aria-pressed": String(on), title, onclick }, color ? el("i", { style: `background:${color}` }) : null, label);
  box.replaceChildren(sw(S.bladeFrom === null, "Original", null, () => pick(null)),
    ...colors.map((c) => sw(S.bladeFrom === c.hue, `${Math.round(c.share * 100)}%`, hex(c.color), () => {
      if (S.bladeFrom !== c.hue) $("blade-color").value = gray(c.color, 1);
      pick(c.hue);
    }, "Replace this color")));
  const src = colors.find((c) => c.hue === S.bladeFrom);
  $("blade-to").hidden = !src;
  if (src) $("blade-quick").replaceChildren(...[["Gray", 1], ["Dark", 0.35]].map(([label, k]) =>
    sw($("blade-color").value === gray(src.color, k), label, gray(src.color, k),
      () => { $("blade-color").value = gray(src.color, k); renderBlade(); })));
  $("blade-hint").textContent = !colors.length ? "This look has no colored areas to replace: plain metal and wood can't be told apart."
    : src ? "Every part drawn in this color changes, so a hilt or scabbard in the same color changes too. Only this weapon is affected."
    : "Pick a color of the look to replace. The percentage is how much of its colored surface uses it.";
}

// ---------- trail picker ----------
const RECOMMENDED = {  // checked in the game
  NS_JinYe_BloodTrail_101: "Blood ribbons",
  NS_ChiYingGuRen_BladeTrail_002: "Crimson slash",
  NS_BaiShan_BladeTrail_Red_102: "Red arc",
};
const KEYWORDS = {
  blood: /blood|red|crimson|xue/i, fire: /fire|flame|burn|huo|yan_?r?u?|lava/i, lightning: /lightning|thunder|lei|electric/i,
  ice: /ice|frost|snow|bing|frozen|cold/i, wind: /wind|feng|air/i, dark: /dark|black|shadow|hei|mo_|demon/i,
};
const PICK_FILTERS = [["fits", "Fits this weapon"], ["hero", "Hero trails"], ...Object.keys(KEYWORDS).map((k) => [k, k[0].toUpperCase() + k.slice(1)])];

function pretty(name) {
  if (RECOMMENDED[name]) return RECOMMENDED[name];
  return name.replace(/^NS_/, "").replace(/([a-z])([A-Z])/g, "$1 $2").split("_").filter(Boolean)
    .map((w, i) => (i === 0 ? w + " \u00B7" : w)).join(" ").replace(/\u00B7 \u00B7/, "\u00B7");
}

// Folder names carry boss names, so groups say only where an effect is safe to use.
function groupOf(t) {
  if (RECOMMENDED[t.name]) return "Recommended";
  return t.player ? "Hero weapons" : "Everything else";
}

function trailByPkg(pkg) {
  return S.data.trails.find((t) => t.pkg === pkg);
}

function renderTrailRows() {
  const base = byKey(S.base);
  $("trails").replaceChildren(...base.trails.map((t) => {
    const chosen = S.trailChoice[t.tag];
    const info = chosen ? trailByPkg(chosen) : null;
    const btn = el("button", { type: "button", class: `trail-btn${chosen ? " changed" : ""}`, onclick: () => openPicker(t.tag),
      "aria-label": `Trail for ${t.tag}: ${chosen ? pretty(info ? info.name : chosen) : "original"}. Change` },
      el("span", { class: "t" }, chosen ? pretty(info ? info.name : chosen.split("/").pop()) : "Original"),
      el("span", { class: "s" }, chosen ? (info ? info.name : chosen) : "now: " + t.name));
    return el("div", { class: "trail" }, el("span", { class: "tagname" }, t.tag), btn);
  }));
}

// While a dialog is open the page behind it can't take focus or clicks.
function setBackdrop(on) {
  for (const n of document.querySelectorAll("header, main, footer")) n.inert = on;
}

function openPicker(tag) {
  S.pickTag = tag;
  S.pickFilters = S.pickFilters || new Set();
  if (byKey(S.base).fades) S.pickFilters.add("fits");
  S.lastFocus = document.activeElement;
  $("picker-title").textContent = `Trail for ${tag}`;
  $("picker-search").value = "";
  $("picker").hidden = $("picker-shade").hidden = false;
  setBackdrop(true);
  renderPicker();
  $("picker-search").focus();
}

function closePicker() {
  $("picker").hidden = $("picker-shade").hidden = true;
  setBackdrop(false);
  if (S.lastFocus) S.lastFocus.focus();
}

function pickTrail(pkg) {
  if (pkg) S.trailChoice[S.pickTag] = pkg;
  else delete S.trailChoice[S.pickTag];
  closePicker();
  renderTrailRows();
}

function renderPicker() {
  const base = byKey(S.base);
  const q = $("picker-search").value.trim().toLowerCase();
  const f = S.pickFilters;
  if (!base.fades) f.delete("fits");  // any trail works on a weapon without fading trails
  $("picker-filters").replaceChildren(...PICK_FILTERS.filter(([k]) => k !== "fits" || base.fades).map(([k, label]) =>
    el("button", { type: "button", class: `chip${f.has(k) ? " on" : ""}`, "aria-pressed": String(f.has(k)),
      onclick: () => { f.has(k) ? f.delete(k) : f.add(k); renderPicker(); } }, label)));
  const current = S.trailChoice[S.pickTag] || "";
  // only fade weapons have a hard requirement; other weapons can use any trail
  const ok = (t) => (!f.has("fits") || !base.fades || t.fade) && (!f.has("hero") || t.player)
    && Object.keys(KEYWORDS).every((k) => !f.has(k) || KEYWORDS[k].test(t.name))
    && (!q || t.name.toLowerCase().includes(q) || pretty(t.name).toLowerCase().includes(q));
  const item = (t) => el("button", { type: "button", class: `pk-item${t.pkg === current ? " current" : ""}`, onclick: () => pickTrail(t.pkg) },
    el("span", {}, el("div", { class: "t" }, pretty(t.name)), el("div", { class: "s" }, t.name)),
    el("span", { class: "marks" }, [t.fade && "fade", t.blade && "blade", t.player && "hero"].filter(Boolean).map((m) => el("i", { class: "pill " + m }, m))));
  const list = S.data.trails.filter(ok);
  const groups = {};
  for (const t of list) (groups[groupOf(t)] ||= []).push(t);
  const names = ["Recommended", "Hero weapons", "Everything else"].filter((g) => groups[g]);
  const orig = byKey(S.base).trails.find((t) => t.tag === S.pickTag);
  const out = [el("button", { type: "button", class: `pk-item${current ? "" : " current"}`, onclick: () => pickTrail(null) },
    el("span", {}, el("div", { class: "t" }, "Original"), el("div", { class: "s" }, orig ? orig.name : "")), el("span"))];
  for (const g of names) out.push(el("div", { class: "pk-group" }, `${g} (${groups[g].length})`), ...groups[g].map(item));
  if (!list.length) out.push(el("div", { class: "muted" }, "Nothing matches. Turn a filter off or change the search."));
  $("picker-list").replaceChildren(...out);
}

function updateAddLabel() {
  const inRecipe = S.base && S.recipe.some((r) => r.base === S.base);
  $("btn-add").textContent = inRecipe ? "Update recipe" : "Add to recipe";
}

function selectBase(key) {
  S.base = key;
  S.browsing = false;
  S.skin = null;
  $("skin-step").hidden = false;
  $("any-type").checked = false;
  renderBases();
  renderSkins();
  renderPreview();
  const existing = S.recipe.find((r) => r.base === key);
  if (existing) loadEntry(existing);
  updateAddLabel();
  renderRecipe();
}

function selectSkin(key) {
  S.skin = key;
  $("scabbard").checked = true;
  renderSkins();
  renderPreview();
}

function loadEntry(e) {
  S.skin = e.skin || null;
  renderSkins();
  renderPreview();
  $("scabbard").checked = !!e.scabbard;
  $("color").value = e.trail_color ? "preset:" + e.trail_color : e.trail_tint ? "tint:" + e.trail_tint : "";
  S.trailChoice = { ...(e.trails || {}) };
  renderTrailRows();
  if (e.blade_color) {
    S.bladeFrom = e.blade_color.from;
    $("blade-color").value = e.blade_color.to;
    renderBlade();
  }
}

// ---------- recipe ----------
function currentEntry() {
  const base = byKey(S.base);
  const e = { base: base.key };
  if (S.skin) {
    const skin = byKey(S.skin);
    e.skin = skin.key;
    if (skin.blades !== base.blades) e.slots = [...Array(Math.min(skin.blades, base.blades)).keys()];
    if ($("scabbard").checked && scabFits(base, skin)) e.scabbard = true;
  }
  if (Object.keys(S.trailChoice).length) e.trails = { ...S.trailChoice };
  const [kind, id] = $("color").value.split(":");
  if (kind === "preset") e.trail_color = id;
  if (kind === "tint") e.trail_tint = id;
  if (S.bladeFrom !== null && byKey(S.skin || S.base).skinnable) e.blade_color = { from: S.bladeFrom, to: $("blade-color").value };
  return e;
}

function describe(e) {
  const bits = [];
  if (e.scabbard) bits.push("scabbard");
  if (e.trails) bits.push(`${Object.keys(e.trails).length} trail${Object.keys(e.trails).length > 1 ? "s" : ""}`);
  if (e.trail_color) bits.push(e.trail_color);
  if (e.trail_tint) bits.push(e.trail_tint + " tint");
  if (e.blade_color) bits.push("blade " + e.blade_color.to);
  return bits.join(" · ") || "look only";
}

function renderRecipe() {
  $("recipe-count").textContent = S.recipe.length;
  if (!S.recipe.length) {
    $("recipe-list").replaceChildren(el("div", { class: "muted" }, "Nothing yet. Pick a base and a look, then \"Add to recipe\"."));
    return;
  }
  $("recipe-list").replaceChildren(...S.recipe.map((e, i) => {
    const b = byKey(e.base) || { name: e.base }, s = e.skin ? byKey(e.skin) || { name: e.skin } : null;
    return el("div", { class: `rcard${S.base === e.base ? " editing" : ""}`, title: "Click to edit", role: "button", tabindex: "0",
      "aria-label": `Edit ${b.name}`, onclick: () => selectBase(e.base),
      onkeydown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); selectBase(e.base); } } },
      picture(b), el("span", { class: "a" }, icon("chevron")), picture(s || b),
      el("div", { class: "txt" }, b.name, el("small", {}, s ? "as " + s.name : "own look"), el("small", {}, describe(e))),
      el("button", { type: "button", class: "x", title: "Remove", "aria-label": `Remove ${b.name} from the recipe`,
        onclick: (ev) => { ev.stopPropagation(); S.recipe.splice(i, 1); renderRecipe(); updateAddLabel(); } }, icon("x")));
  }));
}

function addToRecipe() {
  const e = currentEntry();
  if (Object.keys(e).length === 1) return toast("Nothing to change yet: pick a look, a trail or a color.", true);
  const updating = S.recipe.some((r) => r.base === e.base);
  S.recipe = S.recipe.filter((r) => r.base !== e.base).concat([e]);
  renderRecipe();
  updateAddLabel();
  toast(`${byKey(e.base).name} ${updating ? "updated in" : "added to"} the recipe.`);
}

function recipe() {
  return { pak_name: $("pak").value.trim() || "zzz_Bladesmith_P", weapons: S.recipe };
}

async function build(install) {
  if (!S.recipe.length) return toast("The recipe is empty.", true);
  const buttons = ["btn-build", "btn-install"].map($);
  const pressed = $(install ? "btn-install" : "btn-build");
  const label = pressed.textContent;
  buttons.forEach((b) => (b.disabled = true));
  pressed.setAttribute("aria-busy", "true");
  pressed.textContent = "Building...";
  try {
    const res = await window.pywebview.api.build(recipe(), install);
    if (res.ok) toast(install ? "Built and installed. Start the game!" : "Built: " + res.folder);
    if (res.ok && install) refreshInstalledCount();
    else toast(res.error, true);
  } finally {
    buttons.forEach((b) => (b.disabled = false));
    pressed.removeAttribute("aria-busy");
    pressed.textContent = label;
  }
}

// ---------- first start ----------
function showSetup(setup) {
  document.querySelector("#loading .spinner").hidden = true;
  $("loading-log").textContent = "";
  $("setup").hidden = false;
  $("setup-msg").textContent = setup.message;
  const retry = el("button", { class: "ghost", onclick: () => location.reload() }, "Try again");
  const actions = [];
  if (setup.kind === "game") {
    actions.push(el("button", { class: "primary", onclick: async () => {
      const res = await window.pywebview.api.choose_game_folder();
      if (res.ok) location.reload();
      else if (res.error) $("setup-msg").textContent = res.error;
    } }, "Choose the game folder"));
  } else if (setup.kind === "dotnet") {
    actions.push(el("button", { class: "primary", onclick: () => window.pywebview.api.open_url(setup.url) }, "Download .NET 8 Desktop Runtime"), retry);
  } else {
    actions.push(retry);
  }
  $("setup-actions").replaceChildren(...actions);
}

// ---------- installed paks ----------
async function refreshInstalledCount() {
  S.installed = await window.pywebview.api.installed();
  $("installed-count").textContent = S.installed.length;
  return S.installed;
}

async function openDrawer() {
  S.lastFocus = document.activeElement;
  $("drawer").hidden = $("drawer-shade").hidden = false;
  setBackdrop(true);
  await renderInstalled();
  $("drawer-close").focus();
}

function closeDrawer() {
  $("drawer").hidden = $("drawer-shade").hidden = true;
  setBackdrop(false);
  if (S.lastFocus) S.lastFocus.focus();
}

async function renderInstalled() {
  const list = await refreshInstalledCount();
  if (!list.length) {
    $("installed-list").replaceChildren(el("div", { class: "muted" }, "Nothing installed yet. Build & install a recipe first."));
    return;
  }
  $("installed-list").replaceChildren(...list.map((p) => {
    const lines = (p.recipe.weapons || []).map((e) => {
      const b = byKey(e.base), s = e.skin ? byKey(e.skin) : null;
      const d = describe(e);
      return el("li", {}, `${b ? b.name : e.base}${s ? " as " + s.name : ""}${d === "look only" ? "" : " · " + d}`);
    });
    const remove = el("button", { class: "ghost" }, "Remove");
    remove.addEventListener("click", async () => {
      if (!remove.classList.contains("danger")) {  // two clicks: no browser dialogs inside the app
        remove.classList.add("danger");
        remove.textContent = "Click again to remove";
        setTimeout(() => { remove.classList.remove("danger"); remove.textContent = "Remove"; }, 4000);
        return;
      }
      const res = await window.pywebview.api.uninstall(p.name);
      if (res.ok) { toast(`${p.name} removed. The weapons are back to the original look.`); renderInstalled(); }
      else toast(res.error, true);
    });
    const edit = el("button", { class: "ghost", onclick: () => {
      S.recipe = p.recipe.weapons || [];
      $("pak").value = p.name;
      renderRecipe();
      closeDrawer();
      toast(`Loaded ${p.name}. Change it and press Build & install to update it.`);
    } }, "Edit");
    return el("div", { class: "inst" },
      el("div", { class: "top" }, el("span", { class: "name" }, p.name), el("span", { class: "date" }, p.date)),
      el("ul", {}, lines), el("div", { class: "row" }, edit, remove));
  }));
}

// ---------- boot ----------
async function boot() {
  try {
    S.data = await window.pywebview.api.init();
  } catch (err) {
    $("loading-log").textContent = "Could not read the game: " + err;
    return;
  }
  if (S.data.setup) return showSetup(S.data.setup);
  $("loading").remove();
  renderFilters();
  renderBases();
  renderRecipe();
  $("base-search").addEventListener("input", (e) => { S.query = e.target.value; renderBases(); });
  $("any-type").addEventListener("change", () => S.base && renderSkins());
  $("color").addEventListener("change", (e) => {
    const [kind, id] = e.target.value.split(":");
    const p = kind === "preset" && S.data.presets.find((x) => x.id === id);
    $("color-hint").textContent = p ? p.description : kind === "tint"
      ? `Experimental. Every colored part of this weapon's trails turns ${id}. Some effects keep a bit of their old color, and you'll only see that in the game.` : "";
  });
  $("blade-color").addEventListener("input", renderBlade);
  $("picker-close").replaceChildren(icon("x"));
  $("picker-close").addEventListener("click", closePicker);
  $("picker-shade").addEventListener("click", closePicker);
  $("picker-search").addEventListener("input", renderPicker);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("picker").hidden) closePicker(); });
  $("btn-add").addEventListener("click", addToRecipe);
  $("btn-installed").addEventListener("click", openDrawer);
  $("drawer-close").replaceChildren(icon("x"));
  $("drawer-close").addEventListener("click", closeDrawer);
  $("drawer-shade").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("drawer").hidden) closeDrawer(); });
  refreshInstalledCount();
  $("btn-build").addEventListener("click", () => build(false));
  $("btn-install").addEventListener("click", () => build(true));
  $("btn-save").addEventListener("click", () => window.pywebview.api.save_recipe(recipe()));
  $("btn-open").addEventListener("click", async () => {
    const r = await window.pywebview.api.open_recipe();
    if (!r) return;
    S.recipe = r.weapons || [];
    $("pak").value = r.pak_name || "zzz_Bladesmith_P";
    renderRecipe();
  });
  $("skin-step").hidden = true;  // the look step appears once a base is picked
}

window.addEventListener("pywebviewready", boot);
