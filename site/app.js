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
// The replay starts from a darkened map and uncovers it along the path. Not quite
// opaque, so the shape of the land still shows through.
const DARKNESS_OPACITY = 0.92;
// Longest side of the darkness mask; it is soft-edged, so it needs no finer detail.
const DARKNESS_MAX_PX = 1024;
const DARKNESS_FADE_MS = 900;
// How long a looping replay rests on the finished map before starting again.
const LOOP_PAUSE_MS = 10000;
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");
const tip = document.getElementById("tip");
const playButton = document.getElementById("play");
const scrub = document.getElementById("scrub");
const speedSelect = document.getElementById("speed");
const skipButton = document.getElementById("skip");
const loopBox = document.getElementById("loop");
const loopStatus = document.getElementById("loop-status");

let summary = null;
let view = null;                         // the loaded worldspace
let camera = { zoom: 1, col: 0, row: 0 }; // zoom, and the map point at the canvas centre
let progress = 1;                        // 0..1 through the replay, by walking time
let playing = false;
let lastFrame = 0;
let drawQueued = false;
let darkness = null;                     // the replay's unexplored mask
let darknessAlpha = 0;                   // 1 while replaying, fading to 0 at the end
let fadeStart = 0;
let loopTimer = null;
let loopCountdown = null;
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
  cancelLoop();
  view = { id, stats, markers, relief, fog: tintFog(fog), runs: timeRuns(runs) };
  darkness = makeDarkness(stats);
  markRevealTimes(view.markers, view.runs, stats.reveal_radius_px || 40);
  camera = { zoom: 1, col: stats.width_px / 2, row: stats.height_px / 2 };
  document.getElementById("title").textContent = NAMES[id] || id;
  writeStats(stats);
  document.getElementById("replay").hidden = view.runs.total === 0;
  resize();
  if (reduceMotion || view.runs.total === 0) {
    darknessAlpha = 0;
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

// When the replay first uncovers each location: the earliest moment the path comes
// within sight of it. One the path never reaches -- fast travelled to, or found before
// tracking began -- appears at the end, with the real fog.
function markRevealTimes(markers, runs, radius) {
  const reach = radius * radius;
  for (const marker of markers) {
    marker.revealAt = Infinity;
    for (const run of runs) {
      for (const point of run) {
        if (point.t >= marker.revealAt) break;
        const dx = point.col - marker.col;
        const dy = point.row - marker.row;
        if (dx * dx + dy * dy <= reach) {
          marker.revealAt = point.t;
          break;
        }
      }
    }
  }
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
  tip.hidden = true;
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
  if (darkness && darknessAlpha > 0) {
    ctx.globalAlpha = DARKNESS_OPACITY * darknessAlpha;
    ctx.drawImage(darkness.canvas, 0, 0, w, h);
  }
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
  const until = progress >= 1 ? Infinity : progress * view.runs.total;
  for (const m of view.markers) {
    if (m.revealAt > until) continue;  // not uncovered yet in the replay
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

// The unexplored map as a mask, uncovered along the path up to the replay's time.
// Uncovering only ever adds, so it keeps a cursor and draws just the new stretch; going
// backwards starts again from dark.
function makeDarkness(stats) {
  const fit = Math.min(1, DARKNESS_MAX_PX / Math.max(stats.width_px, stats.height_px));
  const layer = document.createElement("canvas");
  layer.width = Math.max(1, Math.round(stats.width_px * fit));
  layer.height = Math.max(1, Math.round(stats.height_px * fit));
  const mask = {
    canvas: layer, g: layer.getContext("2d"), fit,
    radius: (stats.reveal_radius_px || 40) * fit,
    run: 0, point: 0, until: -1,
  };
  resetDarkness(mask);
  return mask;
}

function resetDarkness(mask) {
  mask.g.globalCompositeOperation = "source-over";
  mask.g.globalAlpha = 1;
  mask.g.fillStyle = COLOURS.fog;
  mask.g.fillRect(0, 0, mask.canvas.width, mask.canvas.height);
  mask.run = 0;
  mask.point = 0;
  mask.until = -1;
}

// A wide faint stroke under the full one gives the seen area a soft edge.
function eraseAlong(mask, run, from, to) {
  const g = mask.g;
  for (const [width, alpha] of [[mask.radius * 2.5, 0.25], [mask.radius * 2, 1]]) {
    g.globalAlpha = alpha;
    g.lineWidth = width;
    g.beginPath();
    g.moveTo(run[from].col * mask.fit, run[from].row * mask.fit);
    // A run of one point still needs a stroke of some length to draw its round cap.
    for (let i = from; i <= to; i++) g.lineTo(run[i].col * mask.fit + 0.01, run[i].row * mask.fit);
    g.stroke();
  }
}

function uncover(until) {
  const mask = darkness;
  if (!mask || !view) return;
  if (until < mask.until) resetDarkness(mask);
  const g = mask.g;
  g.globalCompositeOperation = "destination-out";
  g.lineCap = "round";
  g.lineJoin = "round";
  const runs = view.runs;
  while (mask.run < runs.length) {
    const run = runs[mask.run];
    if (run.length === 0 || run[0].t > until) break;
    let next = mask.point;
    while (next < run.length && run[next].t <= until) next++;
    if (next > mask.point) eraseAlong(mask, run, Math.max(mask.point - 1, 0), next - 1);
    mask.point = next;
    if (next < run.length) break;
    mask.run++;
    mask.point = 0;
  }
  g.globalAlpha = 1;
  mask.until = until;
}

function setProgress(value) {
  progress = Math.min(1, Math.max(0, value));
  scrub.value = Math.round(progress * 1000);
  if (view) uncover(progress * view.runs.total);
  if (progress < 1) darknessAlpha = 1;
  requestDraw();
}

// At the end the darkness gives way to the real fog, which also knows about places
// discovered without walking to them.
function fadeOutDarkness() {
  fadeStart = performance.now();
  const fade = (now) => {
    if (progress < 1) return;  // a new replay began
    darknessAlpha = Math.max(0, 1 - (now - fadeStart) / DARKNESS_FADE_MS);
    requestDraw();
    if (darknessAlpha > 0) requestAnimationFrame(fade);
  };
  requestAnimationFrame(fade);
}

function play() {
  cancelLoop();
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

function finished() {
  pause();
  fadeOutDarkness();
  if (loopBox.checked) scheduleLoop();
}

function step(now) {
  if (!playing) return;
  const elapsed = (now - lastFrame) / 1000;
  lastFrame = now;
  setProgress(progress + (elapsed * Number(speedSelect.value)) / REPLAY_SECONDS);
  if (progress >= 1) {
    finished();
    return;
  }
  requestAnimationFrame(step);
}

function scheduleLoop() {
  cancelLoop();
  let remaining = Math.round(LOOP_PAUSE_MS / 1000);
  loopStatus.textContent = `Restarting in ${remaining} s`;
  loopCountdown = setInterval(() => {
    remaining -= 1;
    loopStatus.textContent = remaining > 0 ? `Restarting in ${remaining} s` : "";
  }, 1000);
  loopTimer = setTimeout(() => {
    cancelLoop();
    if (loopBox.checked) play();
  }, LOOP_PAUSE_MS);
}

function cancelLoop() {
  clearTimeout(loopTimer);
  clearInterval(loopCountdown);
  loopTimer = null;
  loopCountdown = null;
  loopStatus.textContent = "";
}

// Straight to the present, and stays there whether or not looping is on.
function skipToEnd() {
  cancelLoop();
  pause();
  setProgress(1);
  playButton.textContent = "Replay";
  fadeOutDarkness();
}

playButton.addEventListener("click", () => (playing ? pause() : play()));
skipButton.addEventListener("click", skipToEnd);
loopBox.addEventListener("change", () => {
  if (!loopBox.checked) cancelLoop();
  else if (!playing && progress >= 1) scheduleLoop();
});
scrub.addEventListener("input", () => {
  cancelLoop();
  if (playing) pause();
  setProgress(Number(scrub.value) / 1000);
  if (progress >= 1) fadeOutDarkness();
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
// Where the current gesture began, and whether it has turned into a drag or a pinch.
// A gesture that stays put is a tap, which shows the nearest location's name -- the
// only way to read one on a touch screen, where nothing hovers.
let gesture = null;
// How far, in CSS pixels, a finger may wander before a tap becomes a drag.
const TAP_SLOP = 8;
// A fingertip is far blunter than a mouse pointer, so taps reach further for a marker.
const TOUCH_REACH = 24;

canvas.addEventListener("pointerdown", (event) => {
  // Capture keeps a drag going when the finger slides off the map. It throws for a
  // pointer the browser no longer considers active, which must not cost the gesture.
  try {
    canvas.setPointerCapture(event.pointerId);
  } catch {
    // dragging still works while the pointer stays over the map
  }
  pointers.set(event.pointerId, canvasPoint(event));
  if (pointers.size === 1) gesture = { start: canvasPoint(event), tap: true };
  else if (gesture) gesture.tap = false;
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
    if (gesture && gesture.tap) {
      const slop = TAP_SLOP * (canvas.width / canvas.clientWidth);
      if (Math.hypot(point[0] - gesture.start[0], point[1] - gesture.start[1]) <= slop) return;
      gesture.tap = false;
    }
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
  const wasTap = event.type === "pointerup" && pointers.size === 1 && gesture && gesture.tap;
  pointers.delete(event.pointerId);
  if (pointers.size < 2) pinchDistance = 0;
  if (pointers.size === 0) {
    canvas.classList.remove("dragging");
    gesture = null;
  }
  if (wasTap && view) showTip(canvasPoint(event), event.pointerType !== "mouse");
}
canvas.addEventListener("pointerup", release);
canvas.addEventListener("pointercancel", release);
// Touch pointers "leave" as the finger lifts, which would hide a label the moment a
// tap shows it; only a mouse leaving the map means the reader moved away.
canvas.addEventListener("pointerleave", (event) => {
  if (event.pointerType === "mouse") tip.hidden = true;
});

function showTip([x, y], touch = false) {
  const ratio = window.devicePixelRatio || 1;
  let best = null;
  let bestDistance = markerSize(ratio) * 0.75;
  if (touch) bestDistance = Math.max(bestDistance, TOUCH_REACH * ratio);
  const until = progress >= 1 ? Infinity : progress * view.runs.total;
  for (const m of view.markers) {
    if (m.revealAt > until) continue;  // not drawn yet, so not hoverable either
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
