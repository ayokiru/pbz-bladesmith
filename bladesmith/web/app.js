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
      `${base.name} keeps its blade in a different kind of asset, so it can't wear another look yet. Its trails and their colors can still be changed on the right.`));
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
function trailOptions(base, current) {
  const sorted = [...S.data.trails].sort((a, b) => a.name.localeCompare(b.name));
  const ok = base.fades ? sorted.filter((t) => t.fade) : sorted.filter((t) => t.blade);
  const rest = sorted.filter((t) => !ok.includes(t));
  const count = {};
  for (const t of sorted) count[t.name] = (count[t.name] || 0) + 1;
  const opt = (t) => {
    const marks = [t.fade && "fade", t.blade && "blade", t.hero && "hero"].filter(Boolean).join(" ");
    const where = count[t.name] > 1 ? `  (${t.pkg.split("/").slice(-2, -1)[0]})` : "";  // same name in two folders
    return el("option", { value: t.pkg, selected: t.pkg === current }, `${t.name}${where}${marks ? "   [" + marks + "]" : ""}`);
  };
  return [
    el("option", { value: ORIGINAL }, "original"),
    el("optgroup", { label: base.fades ? "Fade-capable (no tail while running)" : "Blade trails (safest look)" }, ok.map(opt)),
    el("optgroup", { label: base.fades ? "Others: will keep trailing the blade" : "Other effects" }, rest.map(opt)),
  ];
}

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
    notes.push(el("div", {}, `${base.name} ends its trails with a fade. Pick effects marked fade, others keep following the blade while you run.`));
  notes.push(el("div", {}, "Stats, perks, moveset and hitboxes always stay with the base weapon."));
  $("pv-notes").replaceChildren(...notes);

  const scab = $("scabbard");
  const hasScab = !!(skin && skin.scabbard);
  scab.closest(".toggle").classList.toggle("off", !hasScab);
  if (!hasScab) scab.checked = false;

  const covered = S.data.presets.filter((p) => base.trails.some((t) => p.systems.includes(t.name.toLowerCase())));
  $("color-opt").hidden = !covered.length;
  $("color").replaceChildren(el("option", { value: "" }, "original"), ...covered.map((p) => el("option", { value: p.id }, p.id)));
  $("color-hint").textContent = "";

  $("trails").replaceChildren(...base.trails.map((t) => {
    const sel = el("select", { "data-tag": t.tag, onchange: (e) => e.target.classList.toggle("changed", !!e.target.value) }, trailOptions(base, ORIGINAL));
    return el("div", { class: "trail" }, el("span", { class: "tagname" }, t.tag), sel, el("span", { class: "orig" }, "now: " + t.name));
  }));
}

function updateAddLabel() {
  const inRecipe = S.base && S.recipe.some((r) => r.base === S.base);
  $("btn-add").textContent = inRecipe ? "Update recipe" : "Add to recipe";
}

// Narrow the long effect lists: every select keeps its current value plus the effects whose name matches.
function filterTrails() {
  const q = $("trail-filter").value.trim().toLowerCase();
  for (const sel of document.querySelectorAll("#trails select")) {
    for (const opt of sel.querySelectorAll("option")) {
      opt.hidden = !!q && opt.value !== "" && opt.value !== sel.value && !opt.textContent.toLowerCase().includes(q);
    }
  }
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
  $("trail-filter").value = "";
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
  $("color").value = e.trail_color || "";
  for (const s of document.querySelectorAll("#trails select")) {
    s.value = (e.trails || {})[s.dataset.tag] || ORIGINAL;
    s.classList.toggle("changed", !!s.value);
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
    if ($("scabbard").checked && skin.scabbard) e.scabbard = true;
  }
  const trails = {};
  for (const s of document.querySelectorAll("#trails select")) if (s.value) trails[s.dataset.tag] = s.value;
  if (Object.keys(trails).length) e.trails = trails;
  if ($("color").value) e.trail_color = $("color").value;
  return e;
}

function describe(e) {
  const bits = [];
  if (e.scabbard) bits.push("scabbard");
  if (e.trails) bits.push(`${Object.keys(e.trails).length} trail${Object.keys(e.trails).length > 1 ? "s" : ""}`);
  if (e.trail_color) bits.push(e.trail_color);
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
  await renderInstalled();
  $("drawer-close").focus();
}

function closeDrawer() {
  $("drawer").hidden = $("drawer-shade").hidden = true;
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
      return el("li", {}, `${b ? b.name : e.base}${s ? " as " + s.name : ""}${e.trail_color ? " \u00B7 " + e.trail_color : ""}`);
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
    const p = S.data.presets.find((x) => x.id === e.target.value);
    $("color-hint").textContent = p ? p.description : "";
  });
  $("btn-add").addEventListener("click", addToRecipe);
  $("btn-installed").addEventListener("click", openDrawer);
  $("drawer-close").replaceChildren(icon("x"));
  $("drawer-close").addEventListener("click", closeDrawer);
  $("drawer-shade").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("drawer").hidden) closeDrawer(); });
  refreshInstalledCount();
  $("trail-filter").addEventListener("input", filterTrails);
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
