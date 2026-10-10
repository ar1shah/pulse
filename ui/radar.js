// Handheld radar renderer for the 800x480 kiosk. One canvas, requestAnimationFrame, no libraries.
// Nothing in frame() allocates: colors are resolved once and the tracks are preallocated.
// Layout and colors live in style.css (read once at startup); enums and the lock cone come from contract.js.
import { CONTRACT_VERSION, TRIAGE, TRIAGE_LABELS, TARGET_IDS, LOCK_CONE, DEFAULT_GATE, HOLD_S } from "./contract.js";

const W = 800;
const H = 480;
const APEX_X = 400;                 // the device, bottom center
const APEX_Y = 474;
const RADIUS = 430;                 // px from the apex to the outer arc
const FOV_DEG = 60;                 // LD2450 half angle
const DEG = Math.PI / 180;

const SWEEP_PASS_MS = 1500;         // one pass, edge to edge
const INTERP_MS = 110;              // a little over one 10 Hz tick, so motion never stalls
const LEAVE_MS = 300;               // fade when a track disappears from the snapshot
const HELD_FLOOR = 0.3;             // held dots never fade below this (still survivors are kept alive)
const HELD_FLOOR_LOCKED = 0.7;
const DOT_R = 8;
const LOCK_R = 15;
const WATCHDOG_MS = 2000;           // no snapshot for this long = NO SIGNAL
const CONNECT_TIMEOUT_MS = 3000;
const BACKOFF_MS = [500, 1000, 2000, 4000, 5000];

// ---- DOM + colors ----

const $ = (id) => document.getElementById(id);
const stage = $("stage");
const canvas = $("radar");
const ctx = canvas.getContext("2d", { alpha: true });
const elBadge = $("badge");
const pillLd = $("pill-ld2450");
const pillC1 = $("pill-c1001");
const pillLdText = pillLd.querySelector("b");
const pillC1Text = pillC1.querySelector("b");
const elVitals = $("vitals");
const elVId = $("v-id");
const elVRange = $("v-range");
const elHeart = $("v-heart");
const elBreath = $("v-breath");
const elNoSignal = $("nosignal");
const elNoSignalSub = $("ns-sub");

const rootStyle = getComputedStyle(document.documentElement);
const cssVar = (name) => rootStyle.getPropertyValue(name).trim();
const C = {
  line: cssVar("--line"),
  ring: cssVar("--ring"),
  zone: cssVar("--zone"),
  text: cssVar("--text"),
  dim: cssVar("--dim"),
  sweep: cssVar("--sweep"),
};
// index: 0 green (moving), 1 amber (still, breathing), 2 gray (not assessed)
const TRIAGE_COLORS = [cssVar("--triage-green"), cssVar("--triage-amber"), cssVar("--triage-gray")];
const FONT = "500 12px " + cssVar("--font");

// legend copy comes from the contract so it cannot drift
for (const el of document.querySelectorAll("#legend [data-triage]")) {
  el.textContent = TRIAGE_LABELS[el.dataset.triage];
}

function triageIndex(triage) {
  return triage === TRIAGE.GREEN ? 0 : triage === TRIAGE.AMBER ? 1 : 2;
}

// ---- state ----

function makeTrack(id) {
  return {
    id, active: false, leaving: false, leaveAt: 0,
    fx: 0, fy: 0, tx: 0, ty: 0, t0: 0,     // from / to position (mm) and when the 'to' arrived
    x: 0, y: 0,                              // current render position (mm)
    tri: 2, locked: false,
    lastSeen: 0, seenAt: 0,
  };
}
const tracks = TARGET_IDS.map(makeTrack);
const seenFlags = new Uint8Array(TARGET_IDS.length);

let gateRange = DEFAULT_GATE.max_range_m;
let gateAngle = DEFAULT_GATE.max_angle_deg;
let halfDeg = Math.min(gateAngle, FOV_DEG);     // half-angle of the drawn wedge
let lockedTrack = null;
let haveSnapshot = false;

let renderScale = 1;
let gridDirty = true;
let pxPerMm = RADIUS / (gateRange * 1000);

// ---- static layer (offscreen, redrawn only on gate / size change) ----

const gridCanvas = document.createElement("canvas");
const gridCtx = gridCanvas.getContext("2d");

const px = (r, deg) => APEX_X + r * Math.sin(deg * DEG);
const py = (r, deg) => APEX_Y - r * Math.cos(deg * DEG);
const cAng = (deg) => (deg - 90) * DEG;          // sector degrees (0 = up) to canvas arc angle

function rebuildGrid() {
  gridCanvas.width = canvas.width;
  gridCanvas.height = canvas.height;
  const g = gridCtx;
  g.setTransform(renderScale, 0, 0, renderScale, 0, 0);
  g.clearRect(0, 0, W, H);
  const scaleM = RADIUS / gateRange;               // px per metre

  // range rings every 1 m
  g.strokeStyle = C.ring;
  g.lineWidth = 1;
  for (let m = 1; m < gateRange - 0.01; m += 1) {
    g.beginPath();
    g.arc(APEX_X, APEX_Y, m * scaleM, cAng(-halfDeg), cAng(halfDeg));
    g.stroke();
  }

  // wedge outline (the sensor's field of view, narrowed to the angle gate)
  g.strokeStyle = C.line;
  g.lineWidth = 1.5;
  g.beginPath();
  g.moveTo(APEX_X, APEX_Y);
  g.lineTo(px(RADIUS, -halfDeg), py(RADIUS, -halfDeg));
  g.arc(APEX_X, APEX_Y, RADIUS, cAng(-halfDeg), cAng(halfDeg));
  g.closePath();
  g.stroke();

  // lock zone: thin dashed outline only
  const cone = LOCK_CONE;
  const rIn = cone.minRangeM * scaleM;
  const rOut = cone.maxRangeM * scaleM;
  const a = cone.maxAngleDeg;
  g.strokeStyle = C.zone;
  g.lineWidth = 1;
  g.globalAlpha = 0.7;
  g.setLineDash([5, 4]);
  g.beginPath();
  g.moveTo(px(rIn, -a), py(rIn, -a));
  g.lineTo(px(rOut, -a), py(rOut, -a));
  g.arc(APEX_X, APEX_Y, rOut, cAng(-a), cAng(a));
  g.lineTo(px(rIn, a), py(rIn, a));
  g.arc(APEX_X, APEX_Y, rIn, cAng(a), cAng(-a), true);
  g.closePath();
  g.stroke();
  g.setLineDash([]);
  g.globalAlpha = 1;

  // ring labels, plain, where each ring meets the left edge (dots sit near the center line, so keep it clear)
  g.font = FONT;
  g.fillStyle = C.dim;
  g.textAlign = "left";
  g.textBaseline = "alphabetic";
  for (let m = 1; m < gateRange - 0.01; m += 1) {
    g.fillText(m + " m", px(m * scaleM, -halfDeg) + 7, py(m * scaleM, -halfDeg) - 5);
  }
  g.fillText((Number.isInteger(gateRange) ? gateRange : gateRange.toFixed(1)) + " m",
    px(RADIUS, -halfDeg) + 7, py(RADIUS, -halfDeg) - 5);

  // the device
  g.fillStyle = C.text;
  g.beginPath();
  g.moveTo(APEX_X, APEX_Y - 10);
  g.lineTo(APEX_X - 6, APEX_Y + 1);
  g.lineTo(APEX_X + 6, APEX_Y + 1);
  g.closePath();
  g.fill();
  gridDirty = false;
}

// ---- snapshots -> state ----

function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}
function setAttr(el, name, value) {
  if (el.getAttribute(name) !== value) el.setAttribute(name, value);
}
function setVital(el, value, amber) {
  if (value === null) {
    setText(el, "settling...");
    el.classList.add("settling");
  } else {
    setText(el, String(value));
    el.classList.remove("settling");
  }
  el.classList.toggle("amber", amber && value !== null);
}

function applySnapshot(s, now) {
  if (s.v !== CONTRACT_VERSION) console.warn("snapshot v" + s.v + ", UI built for v" + CONTRACT_VERSION);

  // gate
  if (s.gate) {
    if (s.gate.max_range_m !== gateRange || s.gate.max_angle_deg !== gateAngle) {
      gateRange = s.gate.max_range_m;
      gateAngle = s.gate.max_angle_deg;
      halfDeg = Math.min(gateAngle, FOV_DEG);
      pxPerMm = RADIUS / (gateRange * 1000);
      gridDirty = true;
    }
  }

  // targets
  seenFlags.fill(0);
  lockedTrack = null;
  for (const t of s.targets) {
    const tr = tracks[t.id - 1];
    if (!tr) continue;
    seenFlags[t.id - 1] = 1;
    if (!tr.active) {
      tr.active = true;
      tr.fx = tr.tx = tr.x = t.x_mm;
      tr.fy = tr.ty = tr.y = t.y_mm;
    } else {
      tr.fx = tr.x;
      tr.fy = tr.y;
      tr.tx = t.x_mm;
      tr.ty = t.y_mm;
    }
    tr.leaving = false;
    tr.t0 = now;
    tr.tri = triageIndex(t.triage);
    tr.locked = t.locked;
    tr.lastSeen = t.last_seen_s;
    tr.seenAt = now;
    if (t.locked) lockedTrack = tr;
  }
  for (let i = 0; i < tracks.length; i++) {
    const tr = tracks[i];
    if (tr.active && !seenFlags[i] && !tr.leaving) {
      tr.leaving = true;
      tr.leaveAt = now;
    }
  }

  // vitals (only what the snapshot says; null stays "settling...")
  const v = s.vitals;
  const hasLock = v.target_id !== null && lockedTrack !== null;
  setAttr(elVitals, "data-state", hasLock ? "locked" : "idle");
  if (hasLock) {
    setText(elVId, String(v.target_id));
    const tgt = s.targets.find((x) => x.id === v.target_id);
    setText(elVRange, tgt ? tgt.range_m.toFixed(1) + " m" : "-");
    const amber = lockedTrack.tri === 1;
    setVital(elHeart, v.heart_bpm, amber);
    setVital(elBreath, v.breath_rpm, amber);
  }

  // status line
  setText(elBadge, s.source.toUpperCase());
  setAttr(elBadge, "data-source", s.source);
  setAttr(pillLd, "data-status", s.sensors.ld2450);
  setText(pillLdText, s.sensors.ld2450);
  setAttr(pillC1, "data-status", s.sensors.c1001);
  setText(pillC1Text, s.sensors.c1001);
}

// ---- connection ----

let ws = null;
let attempt = 0;
let retryTimer = 0;
let connectedAt = 0;
let lastMsgAt = 0;

function showNoSignal(on, sub) {
  elNoSignal.classList.toggle("show", on);
  if (sub) setText(elNoSignalSub, sub);
}

function detach() {
  if (!ws) return;
  ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
  try { ws.close(); } catch (_) { /* already closed */ }
  ws = null;
}

function lost() {
  detach();
  haveSnapshot = false;
  const delay = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
  attempt++;
  showNoSignal(true, "Reconnecting... (attempt " + attempt + ")");
  clearTimeout(retryTimer);
  retryTimer = setTimeout(connect, delay);
}

function connect() {
  detach();
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  connectedAt = performance.now();
  lastMsgAt = connectedAt;
  try {
    ws = new WebSocket(scheme + "://" + location.host + "/ws");
  } catch (_) {
    lost();
    return;
  }
  ws.onopen = () => {
    attempt = 0;
    lastMsgAt = performance.now();
  };
  ws.onmessage = (ev) => {
    let s;
    try { s = JSON.parse(ev.data); } catch (_) { return; }
    if (!s || s.type !== "snapshot") return;
    const now = performance.now();
    lastMsgAt = now;
    applySnapshot(s, now);
    if (!haveSnapshot) {
      haveSnapshot = true;
      showNoSignal(false);
    }
  };
  ws.onclose = lost;
  ws.onerror = lost;
}

setInterval(() => {
  if (!ws) return;
  const now = performance.now();
  if (ws.readyState === WebSocket.CONNECTING && now - connectedAt > CONNECT_TIMEOUT_MS) lost();
  else if (ws.readyState === WebSocket.OPEN && now - lastMsgAt > WATCHDOG_MS) lost();
}, 500);

// ---- frame loop ----

const sweepDeg = (t) => -halfDeg * Math.cos((Math.PI * t) / SWEEP_PASS_MS);

let fpsEl = null;
let fpsFrames = 0;
let fpsSince = 0;

function drawTrack(tr, ts) {
  // alpha + leaving
  let alpha = 1;
  if (tr.lastSeen > 0) {
    const held = tr.lastSeen + (ts - tr.seenAt) / 1000;
    alpha = Math.max(1 - held / HOLD_S, tr.locked ? HELD_FLOOR_LOCKED : HELD_FLOOR);
  }
  if (tr.leaving) {
    const k = 1 - (ts - tr.leaveAt) / LEAVE_MS;
    if (k <= 0) {
      tr.active = false;
      tr.leaving = false;
      tr.locked = false;
      return;
    }
    alpha *= k;
  }

  // position: glide from the previous render position to the new snapshot
  const u = Math.min((ts - tr.t0) / INTERP_MS, 1);
  tr.x = tr.fx + (tr.tx - tr.fx) * u;
  tr.y = tr.fy + (tr.ty - tr.fy) * u;
  const sx = APEX_X + tr.x * pxPerMm;
  const sy = APEX_Y - tr.y * pxPerMm;
  const color = TRIAGE_COLORS[tr.tri];

  ctx.globalAlpha = alpha;
  ctx.fillStyle = color;
  ctx.strokeStyle = color;
  ctx.beginPath();
  ctx.arc(sx, sy, DOT_R, 0, Math.PI * 2);
  if (tr.lastSeen > 0) {            // held: hollow ring
    ctx.lineWidth = 2;
    ctx.stroke();
  } else {
    ctx.fill();
  }
  if (tr.locked) {                  // the one the vitals belong to
    ctx.strokeStyle = C.text;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(sx, sy, LOCK_R, 0, Math.PI * 2);
    ctx.stroke();
  }
}

function frame(ts) {
  requestAnimationFrame(frame);
  if (gridDirty) rebuildGrid();

  ctx.clearRect(0, 0, W, H);
  ctx.globalAlpha = 1;
  ctx.drawImage(gridCanvas, 0, 0, W, H);

  // sweep: one thin line
  const sweep = sweepDeg(ts);
  ctx.strokeStyle = C.sweep;
  ctx.lineWidth = 1.5;
  ctx.globalAlpha = 0.35;
  ctx.beginPath();
  ctx.moveTo(APEX_X, APEX_Y);
  ctx.lineTo(px(RADIUS, sweep), py(RADIUS, sweep));
  ctx.stroke();

  for (let i = 0; i < tracks.length; i++) {
    if (tracks[i].active) drawTrack(tracks[i], ts);
  }
  ctx.globalAlpha = 1;

  if (fpsEl) {
    fpsFrames++;
    if (ts - fpsSince >= 1000) {
      fpsEl.textContent = fpsFrames + " fps";
      fpsFrames = 0;
      fpsSince = ts;
    }
  }
}

// ---- sizing, kiosk guards, boot ----

function fit() {
  const s = Math.min(window.innerWidth / W, window.innerHeight / H);
  stage.style.transform = s === 1 ? "" : "scale(" + s + ")";
  renderScale = Math.min(2, (window.devicePixelRatio || 1) * s);
  canvas.width = Math.round(W * renderScale);
  canvas.height = Math.round(H * renderScale);
  ctx.setTransform(renderScale, 0, 0, renderScale, 0, 0);
  gridDirty = true;
}
window.addEventListener("resize", fit);

const stop = (e) => e.preventDefault();
document.addEventListener("contextmenu", stop);
document.addEventListener("selectstart", stop);
document.addEventListener("dragstart", stop);
document.addEventListener("gesturestart", stop);
document.addEventListener("gesturechange", stop);
document.addEventListener("wheel", (e) => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });
document.addEventListener("touchstart", (e) => { if (e.touches.length > 1) e.preventDefault(); }, { passive: false });
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && "+-=0".includes(e.key)) e.preventDefault();
});

if (new URLSearchParams(location.search).get("fps") === "1") {
  fpsEl = document.createElement("div");
  fpsEl.id = "fps";
  stage.appendChild(fpsEl);
}

fit();
showNoSignal(true, "Connecting...");
connect();
requestAnimationFrame(frame);
