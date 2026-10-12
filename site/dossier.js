// The character behind the map: SPECIAL, perks, quests, inventory, timeline and load
// order, from data/player.json and data/timeline.json. Absent files mean an older
// companion, or a player who has not played since installing it: nothing is shown.
"use strict";

(function () {
  const root = document.getElementById("dossier");
  const tabBar = document.getElementById("tabs");
  const tabs = [];  // { id, title, badge }, in order

  // Builds an element. Text always goes in as text, never as markup.
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else node.setAttribute(key, value === true ? "" : value);
    }
    // Flattened all the way, so sections can pass lists of lists of nodes.
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  // A Lucide icon from the bundled icons.js, which is ours rather than visitor input.
  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "icon");
    // Only ever a bundled icon: the name comes from data, so it is looked up as an own
    // key, and anything else -- "constructor", say -- falls back to the plain pin.
    svg.innerHTML = Object.prototype.hasOwnProperty.call(ICONS, name) ? ICONS[name] : ICONS["map-pin"];
    return svg;
  }

  const number = (value) => Number(value).toLocaleString();

  async function getJson(path) {
    const response = await fetch(path, { cache: "no-cache" });
    if (!response.ok) throw new Error(`${path}: ${response.status}`);
    return response.json();
  }

  // A section is a tab's panel. The badge is a small count on the tab itself, a hint
  // of what is behind it.
  function section(id, title, badge, ...body) {
    tabs.push({ id, title, badge });
    return el("section", { id: `panel-${id}`, class: `part part-${id}`, role: "tabpanel",
      "aria-labelledby": `tab-${id}`, hidden: true }, el("h2", {}, title), body);
  }

  // --- character -------------------------------------------------------------------

  function character(p) {
    const xp = p.xp || {};
    const bar = el("div", { class: "meter", role: "progressbar", "aria-valuemin": 0,
      "aria-valuemax": 100, "aria-valuenow": Math.round((xp.progress || 0) * 100),
      "aria-label": `Progress to level ${p.level + 1}` });
    bar.append(el("span", { style: `width:${((xp.progress || 0) * 100).toFixed(1)}%` }));

    const special = el("ol", { class: "special" }, (p.special || []).map((s) => {
      const bonus = s.current - s.base;
      const track = el("span", { class: "track" },
        el("span", { class: "base", style: `width:${Math.min(s.base, 15) / 15 * 100}%` }),
        bonus > 0 ? el("span", { class: "bonus", style: `width:${Math.min(bonus, 15) / 15 * 100}%` }) : null);
      return el("li", {},
        el("span", { class: "letter", title: s.label }, s.label[0]),
        el("span", { class: "label" }, s.label),
        track,
        el("span", { class: "value" }, String(s.current), bonus > 0 ? el("small", {}, ` (${s.base}+${bonus})`) : null));
    }));

    const stats = p.stats || {};
    const facts = [
      ["Health", stats.health && `${number(Math.round(stats.health.current))} / ${number(stats.health.max)}`],
      ["Action points", stats.action_points && number(Math.round(stats.action_points.current))],
      ["Radiation", stats.rads && number(Math.round(stats.rads.current))],
      ["Caps", number(p.caps)],
      ["Carry weight", stats.carry_weight && number(Math.round(stats.carry_weight.current))],
      ["Unspent perk points", p.perk_points || null],
      ["Played for", p.playtime_hours ? `${number(Math.round(p.playtime_hours))} hours` : null],
      ["In-game date", p.game_date || null],
      ["Last seen at", p.location || null],
      ["Travelling with", (p.companions || []).join(" and ") || "Nobody"],
    ].filter(([, value]) => value !== null && value !== undefined && value !== "");

    return section("character", "Character", `Level ${p.level}`,
      el("div", { class: "who" },
        el("p", { class: "name" }, p.name),
        el("p", { class: "level" }, el("span", { class: "figure" }, String(p.level)), " level"),
        bar,
        el("p", { class: "xp" }, xp.next_level
          ? `${number(xp.next_level - xp.level_start)} XP to level ${p.level + 1}, ${Math.round((xp.progress || 0) * 100)}% of the way`
          : "")),
      special,
      el("dl", { class: "facts" }, facts.flatMap(([label, value]) => [el("dt", {}, label), el("dd", {}, value)])));
  }

  // --- perks -----------------------------------------------------------------------

  function pips(rank, ranks) {
    const box = el("span", { class: "pips", "aria-label": `rank ${rank} of ${ranks}` });
    for (let i = 0; i < ranks; i++) box.append(el("span", { class: i < rank ? "on" : "" }));
    return box;
  }

  function perks(p) {
    const groups = (p.perks || []).map((group) => el("div", { class: "tree" },
      el("h3", {}, group.special),
      el("ul", {}, group.perks.map((perk) => el("li", {},
        el("span", {}, perk.name), pips(perk.rank, perk.ranks))))));
    const magazines = (p.magazines || []).length ? el("div", { class: "tree" },
      el("h3", {}, "Magazines"),
      el("ul", {}, p.magazines.map((m) => el("li", {},
        el("span", {}, m.name),
        m.issues ? el("span", { class: "issues" }, m.issues.map((n) => `#${n}`).join(" ")) : pips(m.rank, m.ranks))))) : null;
    const bobbleheads = (p.bobbleheads || []).length ? el("div", { class: "tree" },
      el("h3", {}, `Bobbleheads, ${p.bobbleheads.length} of 20`),
      el("ul", { class: "inline" }, p.bobbleheads.map((b) => el("li", {}, b)))) : null;
    if (!groups.length && !magazines && !bobbleheads) return null;
    const perkCount = (p.perks || []).reduce((sum, group) => sum + group.perks.length, 0);
    return section("perks", "Perks", perkCount ? String(perkCount) : null,
      el("div", { class: "trees" }, groups, magazines, bobbleheads));
  }

  // --- quests ----------------------------------------------------------------------

  function quests(p) {
    const q = p.quests || { active: [], finished: [] };
    if (!q.active.length && !q.finished.length) return null;
    const active = el("ul", { class: "active" }, q.active.map((quest) => el("li", {},
      el("p", { class: "quest" }, el("span", {}, quest.name), quest.misc ? null : el("span", { class: "tag" }, quest.type)),
      quest.objectives.length ? el("ul", { class: "objectives" }, quest.objectives.map((o) => el("li", {}, o))) : null)));

    const byType = new Map();
    for (const quest of q.finished) {
      if (!byType.has(quest.type)) byType.set(quest.type, []);
      byType.get(quest.type).push(quest);
    }
    const finished = [...byType.entries()].map(([type, list]) => el("details", {},
      el("summary", {}, `${type}`, el("span", { class: "count" }, String(list.length))),
      el("ul", { class: "finished" }, list.map((quest) => el("li", { class: quest.failed ? "failed" : "" },
        quest.name, quest.failed ? el("span", { class: "tag" }, "Failed") : null)))));

    return section("quests", "Quests", `${q.active.length} active`,
      el("h3", {}, `In progress, ${q.active.length}`), active,
      el("h3", {}, `Finished, ${q.finished.length}`), finished);
  }

  // --- inventory -------------------------------------------------------------------

  function inventory(p) {
    const categories = p.inventory || [];
    if (!categories.length) return null;
    const filter = el("input", { type: "search", class: "filter", placeholder: "Find an item",
      "aria-label": "Find an item in the inventory" });
    const blocks = categories.map((category) => {
      const rows = category.items.map((item) => el("li", { class: item.equipped ? "equipped" : "", "data-name": item.name.toLowerCase() },
        el("span", {}, item.name),
        item.equipped ? el("span", { class: "tag" }, "Equipped") : null,
        el("span", { class: "count" }, item.count > 1 ? number(item.count) : "")));
      const total = category.items.reduce((sum, item) => sum + item.count, 0);
      return el("details", { open: category.category === "Weapons" || category.category === "Apparel" },
        el("summary", {}, category.category, el("span", { class: "count" }, number(total))),
        el("ul", { class: "items" }, rows));
    });
    filter.addEventListener("input", () => {
      const needle = filter.value.trim().toLowerCase();
      for (const block of blocks) {
        let shown = 0;
        for (const row of block.querySelectorAll("li")) {
          const match = !needle || row.dataset.name.includes(needle);
          row.hidden = !match;
          shown += match ? 1 : 0;
        }
        block.hidden = shown === 0;
        if (needle && shown) block.open = true;
      }
    });
    const lines = categories.reduce((sum, category) => sum + category.items.length, 0);
    return section("inventory", "Inventory", number(lines), filter, blocks);
  }

  // --- timeline --------------------------------------------------------------------

  function timeline(events) {
    if (!events.length) return null;
    const days = new Map();
    for (const event of events) {
      const day = new Date(event.at).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
      if (!days.has(day)) days.set(day, []);
      days.get(day).push(event);
    }
    const list = [...days.entries()].map(([day, list]) => el("li", { class: "day" },
      el("h3", {}, day),
      el("ol", {}, list.map((event) => el("li", { class: `event event-${event.kind}` },
        icon(event.icon),
        el("span", { class: "text" }, event.text),
        el("span", { class: "when" }, [
          new Date(event.at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }),
          event.game_date ? `in game ${event.game_date}` : null,
        ].filter(Boolean).join(", ")))))));
    return section("timeline", "Timeline", String(events.length), el("ol", { class: "days" }, list));
  }

  // --- mods ------------------------------------------------------------------------

  function mods(p) {
    const m = p.mods || {};
    const groups = m.groups || [];
    if (!groups.length && !(m.f4se || []).length) return null;
    const total = groups.reduce((sum, group) => sum + group.plugins.length, 0);
    const blocks = groups.map((group) => el("details", { open: group.label === "Mods" },
      el("summary", {}, group.label, el("span", { class: "count" }, String(group.plugins.length))),
      el("ol", { class: "load-order" }, group.plugins.map((plugin) => el("li", {},
        el("span", { class: "slot" }, plugin.light
          ? `FE ${plugin.index.toString(16).toUpperCase().padStart(3, "0")}`
          : plugin.index.toString(16).toUpperCase().padStart(2, "0")),
        el("span", {}, plugin.name))))));
    const f4se = (m.f4se || []).length ? el("details", {},
      el("summary", {}, "Script extender plugins", el("span", { class: "count" }, String(m.f4se.length))),
      el("ul", { class: "load-order" }, m.f4se.map((dll) => el("li", {}, el("span", {}, dll))))) : null;

    if (!m.mo2) {
      return section("mods", "Mods", String(total), el("p", { class: "lede" }, `${total} plugins, in load order.`), blocks, f4se);
    }
    // Every enabled mod as Mod Organizer lists it, grouped by the player's separators,
    // with the plugins and DLLs each one brings. The load order follows for detail.
    const mo2 = m.mo2.groups.map((group) => el("details", {},
      el("summary", {}, group.label, el("span", { class: "count" }, String(group.mods.length))),
      el("ul", { class: "mod-list" }, group.mods.map((mod) => el("li", {},
        el("span", {}, mod.name),
        mod.plugins.length || mod.dlls.length
          ? el("span", { class: "files" }, [...mod.plugins, ...mod.dlls].join(", "))
          : null)))));
    const unmanaged = (m.mo2.unmanaged || []).length ? el("details", {},
      el("summary", {}, "DLC and Creation Club", el("span", { class: "count" }, String(m.mo2.unmanaged.length))),
      el("ul", { class: "mod-list" }, m.mo2.unmanaged.map((name) => el("li", {}, el("span", {}, name))))) : null;
    return section("mods", "Mods", String(m.mo2.enabled),
      el("p", { class: "lede" }, `${m.mo2.enabled} mods enabled in Mod Organizer, ${total} plugins in load order.`),
      mo2, unmanaged,
      el("h3", {}, "Load order"), blocks, f4se);
  }

  async function start() {
    let player;
    try {
      player = await getJson("data/player.json");
    } catch {
      return;  // no character published
    }
    let events = [];
    try {
      events = await getJson("data/timeline.json");
    } catch {
      events = [];
    }
    const parts = [character(player), perks(player), quests(player), inventory(player),
      timeline(events), mods(player)].filter(Boolean);
    if (!parts.length) return;
    root.append(...parts);
    root.hidden = false;
    makeTabs();
  }

  // --- tabs ------------------------------------------------------------------------

  // The map is the first tab and the default; each section is another. The address
  // follows the tab (#quests), so a tab can be linked to and the back button works.
  function makeTabs() {
    for (const { id, title, badge } of tabs) {
      const button = el("button", { type: "button", role: "tab", id: `tab-${id}`,
        "aria-controls": `panel-${id}`, "aria-selected": "false", tabindex: "-1" },
        title, badge ? el("span", { class: "badge" }, badge) : null);
      button.addEventListener("click", () => select(id, true));
      tabBar.append(button);
    }
    document.getElementById("tab-map").addEventListener("click", () => select("map", true));
    tabBar.addEventListener("keydown", moveFocus);
    window.addEventListener("popstate", () => select(fromAddress(), false));
    tabBar.hidden = false;
    select(fromAddress(), false);
  }

  function ids() {
    return ["map", ...tabs.map((tab) => tab.id)];
  }

  function fromAddress() {
    const id = decodeURIComponent(location.hash.slice(1));
    return ids().includes(id) ? id : "map";
  }

  function select(id, remember) {
    for (const key of ids()) {
      const on = key === id;
      document.getElementById(`panel-${key}`).hidden = !on;
      const tab = document.getElementById(`tab-${key}`);
      tab.setAttribute("aria-selected", String(on));
      tab.tabIndex = on ? 0 : -1;
    }
    if (remember) {
      const address = id === "map" ? location.pathname + location.search : `#${id}`;
      if (address !== location.hash) history.pushState(null, "", address);
      tabBar.scrollIntoView({ block: "nearest" });
    }
  }

  // Arrow keys move between tabs, as tab lists do everywhere else.
  function moveFocus(event) {
    const order = ids();
    const current = order.indexOf(document.activeElement.id.replace(/^tab-/, ""));
    if (current < 0) return;
    const next = { ArrowRight: current + 1, ArrowLeft: current - 1, Home: 0, End: order.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const id = order[(next + order.length) % order.length];
    select(id, true);
    document.getElementById(`tab-${id}`).focus();
  }

  start();
})();
