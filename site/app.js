// Draws one published worldspace: a relief map rendered from the game's terrain, the
// fog, discovered locations, and the path walked, which replays itself on load.
// Everything comes from data/, written by the FoggyMap companion; this page only reads it.
"use strict";

const NAMES = {
  Commonwealth: "The Commonwealth",
  DLC03FarHarbor: "Far Harbor",
  NukaWorld: "Nuka-World",
};
const COLOURS = {
  water: "#1F2B33", fog: "#0F161B", trail: "#F2C14E", bone: "#E8E2D2",
};
// Seconds the whole replay takes at normal speed, however long the walk really was.
const REPLAY_SECONDS = 40;
// The relief has about one sample per map pixel; beyond this it only gets softer.
const MAX_ZOOM = 6;
// Unexplored ground stays dim but legible: the geography is what makes the map readable.
const FOG_OPACITY = 0.85;
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");
const tip = document.getElementById("tip");
const playButton = document.getElementById("play");
const scrub = document.getElementById("scrub");
const speedSelect = document.getElementById("speed");

let summary = null;
let view = null;                         // the loaded worldspace
let camera = { zoom: 1, col: 0, row: 0 }; // zoom, and the map point at the canvas centre
let progress = 1;                        // 0..1 through the replay, by walking time
let playing = false;
let lastFrame = 0;
let drawQueued = false;
const iconImages = new Map();

async function getJson(path) {
  const response = await fetch(path, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`${src}: could not load`));
    image.src = src;
  });
}

function dataImage(path) {
  return loadImage(`${path}?v=${encodeURIComponent(summary.published_at)}`);
}

async function start() {
  try {
    summary = await getJson("data/summary.json");
  } catch {
    showEmpty("Nothing has been published yet. Progress appears here after the first hour of play.");
    return;
  }
  const ids = Object.keys(summary.worldspaces);
  if (ids.length === 0) {
    showEmpty("Nothing has been explored yet. Progress appears here after the first hour of play.");
    return;
  }
  const picker = document.getElementById("picker");
  for (const id of ids) {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = NAMES[id] || id;
    picker.append(option);
  }
  document.getElementById("picker-wrap").hidden = ids.length < 2;
  picker.addEventListener("change", () => show(picker.value));
  await show(ids[0]);
}

function showEmpty(text) {
  const stats = document.getElementById("stats");
  stats.replaceChildren();
  const p = document.createElement("p");
  p.className = "empty";
  p.textContent = text;
  stats.append(p);
}

async function show(id) {
  const folder = `data/${id}`;
  const stats = summary.worldspaces[id];
  const [runs, markers, fog, relief] = await Promise.all([
    getJson(`${folder}/path.json`),
    getJson(`${folder}/markers.json`),
    dataImage(`${folder}/fog.png`),
    stats.relief ? dataImage(`${folder}/relief.webp`) : Promise.resolve(null),
  ]);
  await loadIcons(markers);
  view = { id, stats, markers, relief, fog: tintFog(fog), runs: timeRuns(runs) };
  camera = { zoom: 1, col: stats.width_px / 2, row: stats.height_px / 2 };
  document.getElementById("title").textContent = NAMES[id] || id;
  writeStats(stats);
  document.getElementById("replay").hidden = view.runs.total === 0;
  resize();
  if (reduceMotion || view.runs.total === 0) {
    setProgress(1);
  } else {
    setProgress(0);
    play();
  }
}

// Each point gets the walking time at which it was reached, so the replay keeps the
// rhythm of the walk: lingering somewhere shows as the trail pausing there.
function timeRuns(runs) {
  let clock = 0;
  const timed = runs.map((run) => run.map(([col, row, pause], index) => {
    if (index > 0) clock += Math.max(pause, 0.05);
    return { col, row, t: clock };
  }));
  timed.total = clock;
  return timed;
}

// The fog arrives as black with opacity; recolour it to the page's smoke, once.
function tintFog(image) {
  const layer = document.createElement("canvas");
  layer.width = image.width;
  layer.height = image.height;
  const g = layer.getContext("2d");
  g.drawImage(image, 0, 0);
  g.globalCompositeOperation = "source-in";
  g.fillStyle = COLOURS.fog;
  g.fillRect(0, 0, layer.width, layer.height);
  return layer;
}

// Lucide icons from icons.js, drawn dark so they read on a pale disc.
async function loadIcons(markers) {
  const wanted = new Set(markers.map((m) => m.icon));
  await Promise.all([...wanted].filter((name) => !iconImages.has(name)).map(async (name) => {
    const body = ICONS[name] || ICONS["map-pin"];
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" `
      + `stroke="${COLOURS.fog}" stroke-width="2.25" stroke-linecap="round" `
      + `stroke-linejoin="round">${body}</svg>`;
    iconImages.set(name, await loadImage(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`));
  }));
}

function writeStats(stats) {
  const box = document.getElementById("stats");
  box.replaceChildren();
  const figure = document.createElement("p");
  figure.className = "figure";
  figure.textContent = `${Math.round(stats.percent_explored)}%`;
  const explored = document.createElement("p");
  explored.textContent = "of the map explored on foot.";
  const found = document.createElement("p");
  found.append("Found ", strong(`${stats.pois_found} of ${stats.pois_total}`), " locations.");
  const when = document.createElement("p");
  when.append("Last updated ", strong(relativeTime(summary.published_at)), ".");
  box.append(figure, explored, found, when);
}

function strong(text) {
  const element = document.createElement("strong");
  element.textContent = text;
  return element;
}

function relativeTime(iso) {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 2) return "just now";
  if (minutes < 90) return `${minutes} minutes ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours} hours ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
}

// --- camera ------------------------------------------------------------------------

// Canvas pixels per map pixel at the current zoom.
function scale() {
  return (canvas.width / view.stats.width_px) * camera.zoom;
}

function toScreen(col, row) {
  const s = scale();
  return [(col - camera.col) * s + canvas.width / 2, (row - camera.row) * s + canvas.height / 2];
}

function toMap(x, y) {
  const s = scale();
  return [(x - canvas.width / 2) / s + camera.col, (y - canvas.height / 2) / s + camera.row];
}

// Keeps the map filling the view: no panning off into empty space.
function clampCamera() {
  const { width_px: w, height_px: h } = view.stats;
  camera.zoom = Math.min(MAX_ZOOM, Math.max(1, camera.zoom));
  const halfW = w / (2 * camera.zoom);
  const halfH = h / (2 * camera.zoom);
  camera.col = Math.min(w - halfW, Math.max(halfW, camera.col));
  camera.row = Math.min(h - halfH, Math.max(halfH, camera.row));
}

// Zoom by ``factor`` keeping the map point under (x, y) canvas pixels where it is.
function zoomAt(factor, x, y) {
  if (!view) return;
  const [col, row] = toMap(x, y);
  camera.zoom *= factor;
  clampCamera();
  const [nx, ny] = toScreen(col, row);
  const s = scale();
  camera.col += (nx - x) / s;
  camera.row += (ny - y) / s;
  clampCamera();
  requestDraw();
}

// --- drawing -----------------------------------------------------------------------

function resize() {
  if (!view) return;
  const size = canvas.clientWidth;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(size * ratio);
  canvas.height = Math.round(size * ratio);
  draw();
}

function requestDraw() {
  if (drawQueued) return;
  drawQueued = true;
  requestAnimationFrame(() => {
    drawQueued = false;
    draw();
  });
}

function draw() {
  if (!view) return;
  const { width_px: w, height_px: h } = view.stats;
  const s = scale();
  const ratio = window.devicePixelRatio || 1;

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = COLOURS.water;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const [ox, oy] = toScreen(0, 0);
  ctx.setTransform(s, 0, 0, s, ox, oy);
  ctx.imageSmoothingQuality = "high";
  if (view.relief) ctx.drawImage(view.relief, 0, 0, w, h);
  ctx.globalAlpha = FOG_OPACITY;
  ctx.drawImage(view.fog, 0, 0, w, h);
  ctx.globalAlpha = 1;

  const head = drawPath(Math.max(1.6, 1.4 * ratio) / s);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  drawMarkers(ratio);
  drawWalker(head, ratio);
}

// The path up to the replay's current time, in map space. Returns the walker's spot.
function drawPath(lineWidth) {
  const until = progress * view.runs.total;
  let head = null;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.strokeStyle = COLOURS.trail;
  ctx.lineWidth = lineWidth;
  for (const run of view.runs) {
    if (run.length === 0 || run[0].t > until) break;
    ctx.beginPath();
    ctx.moveTo(run[0].col, run[0].row);
    head = run[0];
    for (let i = 1; i < run.length && run[i].t <= until; i++) {
      ctx.lineTo(run[i].col, run[i].row);
      head = run[i];
    }
    ctx.stroke();
  }
  return head;
}

// Icons stay a readable size on screen, growing a little as you zoom in. On a small
// map they start as dots, since a phone-width Commonwealth has no room for glyphs.
function markerSize(ratio) {
  const base = Math.min(15, Math.max(7, canvas.clientWidth / 55));
  return Math.min(26, base + 4 * Math.log2(camera.zoom)) * ratio;
}

const MIN_GLYPH_PX = 11;

function drawMarkers(ratio) {
  const size = markerSize(ratio);
  for (const m of view.markers) {
    const [x, y] = toScreen(m.col, m.row);
    if (x < -size || y < -size || x > canvas.width + size || y > canvas.height + size) continue;
    ctx.fillStyle = COLOURS.bone;
    ctx.strokeStyle = COLOURS.fog;
    ctx.lineWidth = ratio;
    ctx.beginPath();
    ctx.arc(x, y, size / 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    const icon = iconImages.get(m.icon);
    if (icon && size / ratio >= MIN_GLYPH_PX) {
      const inner = size * 0.62;
      ctx.drawImage(icon, x - inner / 2, y - inner / 2, inner, inner);
    }
  }
}

// The walker during replay, or where the player last stood once it is over.
function drawWalker(head, ratio) {
  const last = view.stats.last_position;
  const at = progress < 1 ? head : (last ? { col: last[0], row: last[1] } : head);
  if (!at) return;
  const [x, y] = toScreen(at.col, at.row);
  const r = 3.5 * ratio;
  ctx.fillStyle = COLOURS.trail;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = COLOURS.trail;
  ctx.lineWidth = 1.5 * ratio;
  ctx.beginPath();
  ctx.arc(x, y, r * 2.6, 0, Math.PI * 2);
  ctx.stroke();
}

// --- replay ------------------------------------------------------------------------

function setProgress(value) {
  progress = Math.min(1, Math.max(0, value));
  scrub.value = Math.round(progress * 1000);
  requestDraw();
}

function play() {
  if (progress >= 1) setProgress(0);
  playing = true;
  playButton.textContent = "Pause";
  lastFrame = performance.now();
  requestAnimationFrame(step);
}

function pause() {
  playing = false;
  playButton.textContent = progress >= 1 ? "Replay" : "Resume";
}

function step(now) {
  if (!playing) return;
  const elapsed = (now - lastFrame) / 1000;
  lastFrame = now;
  setProgress(progress + (elapsed * Number(speedSelect.value)) / REPLAY_SECONDS);
  if (progress >= 1) {
    pause();
    return;
  }
  requestAnimationFrame(step);
}

playButton.addEventListener("click", () => (playing ? pause() : play()));
scrub.addEventListener("input", () => {
  if (playing) pause();
  setProgress(Number(scrub.value) / 1000);
  playButton.textContent = progress >= 1 ? "Replay" : "Resume";
});

// --- zoom, pan and location names --------------------------------------------------

function canvasPoint(event) {
  const rect = canvas.getBoundingClientRect();
  const ratio = canvas.width / rect.width;
  return [(event.clientX - rect.left) * ratio, (event.clientY - rect.top) * ratio];
}

canvas.addEventListener("wheel", (event) => {
  event.preventDefault();
  const [x, y] = canvasPoint(event);
  zoomAt(Math.exp(-event.deltaY * 0.0015), x, y);
}, { passive: false });

canvas.addEventListener("dblclick", (event) => {
  const [x, y] = canvasPoint(event);
  zoomAt(event.shiftKey ? 0.5 : 2, x, y);
});

const pointers = new Map();
let pinchDistance = 0;

canvas.addEventListener("pointerdown", (event) => {
  canvas.setPointerCapture(event.pointerId);
  pointers.set(event.pointerId, canvasPoint(event));
  if (pointers.size === 2) {
    const [a, b] = [...pointers.values()];
    pinchDistance = Math.hypot(a[0] - b[0], a[1] - b[1]);
  }
  canvas.classList.add("dragging");
});

canvas.addEventListener("pointermove", (event) => {
  if (!view) return;
  const point = canvasPoint(event);
  const previous = pointers.get(event.pointerId);
  if (previous) {
    pointers.set(event.pointerId, point);
    tip.hidden = true;
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const distance = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (pinchDistance > 0) zoomAt(distance / pinchDistance, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
      pinchDistance = distance;
    } else {
      const s = scale();
      camera.col -= (point[0] - previous[0]) / s;
      camera.row -= (point[1] - previous[1]) / s;
      clampCamera();
      requestDraw();
    }
    return;
  }
  showTip(point);
});

function release(event) {
  pointers.delete(event.pointerId);
  if (pointers.size < 2) pinchDistance = 0;
  if (pointers.size === 0) canvas.classList.remove("dragging");
}
canvas.addEventListener("pointerup", release);
canvas.addEventListener("pointercancel", release);
canvas.addEventListener("pointerleave", () => { tip.hidden = true; });

function showTip([x, y]) {
  const ratio = window.devicePixelRatio || 1;
  let best = null;
  let bestDistance = markerSize(ratio) * 0.75;
  for (const m of view.markers) {
    const [mx, my] = toScreen(m.col, m.row);
    const distance = Math.hypot(mx - x, my - y);
    if (distance < bestDistance) {
      best = { marker: m, x: mx, y: my };
      bestDistance = distance;
    }
  }
  if (!best) {
    tip.hidden = true;
    return;
  }
  tip.replaceChildren();
  const name = document.createElement("strong");
  name.textContent = best.marker.name;
  const kind = document.createElement("span");
  kind.textContent = best.marker.kind;
  tip.append(name, kind);
  const cssRatio = canvas.clientWidth / canvas.width;
  tip.style.left = `${best.x * cssRatio}px`;
  tip.style.top = `${(best.y - markerSize(ratio) / 2) * cssRatio}px`;
  tip.hidden = false;
}

function zoomButton(id, factor) {
  document.getElementById(id).addEventListener("click", () => {
    zoomAt(factor, canvas.width / 2, canvas.height / 2);
  });
}
zoomButton("zoom-in", 2);
zoomButton("zoom-out", 0.5);
document.getElementById("zoom-fit").addEventListener("click", () => {
  if (!view) return;
  camera = { zoom: 1, col: view.stats.width_px / 2, row: view.stats.height_px / 2 };
  requestDraw();
});

new ResizeObserver(resize).observe(canvas);
start();
