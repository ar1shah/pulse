// Handheld radar renderer for the 800x480 kiosk. One canvas, requestAnimationFrame, no libraries.
// Nothing in frame() allocates: colors and fonts are resolved once, tracks and buffers are preallocated.
// Layout and colors live in style.css (read once at startup); enums and the lock cone come from contract.js.
import { CONTRACT_VERSION, TRIAGE, TARGET_IDS, LOCK_CONE, DEFAULT_GATE, HOLD_S } from "./contract.js";

const W = 800;
const H = 480;
const APEX_X = 400;                 // the device, bottom center
const APEX_Y = 474;
const RADIUS = 416;                 // px from the apex to the outer arc
const FOV_DEG = 60;                 // LD2450 half angle
const LABEL_DEG = -45;              // range labels sit on this spoke
const DEG = Math.PI / 180;

const SWEEP_PASS_MS = 1500;         // one pass, edge to edge
const TRAIL_SLICES = 16;
const TRAIL_SLICE_MS = 16;
const INTERP_MS = 110;              // a little over one 10 Hz tick, so motion never stalls
const LEAVE_MS = 300;               // fade when a track disappears from the snapshot
const HELD_FLOOR = 0.3;             // held dots never fade below this (still survivors are kept alive)
const HELD_FLOOR_LOCKED = 0.7;
const TRAIL_N = 12;
const TRAIL_MS = 80;
const PING_MS = 650;
const ECG_N = 168;                  // samples across the trace box
const ECG_STEP_MS = 12;
const ECG_W = 88;
const ECG_H = 40;
const WATCHDOG_MS = 2000;           // no snapshot for this long = NO SIGNAL
const CONNECT_TIMEOUT_MS = 3000;
const BACKOFF_MS = [500, 1000, 2000, 4000, 5000];

// ---- DOM + colors ----

const $ = (id) => document.getElementById(id);
const stage = $("stage");
const canvas = $("radar");
const ctx = canvas.getContext("2d", { alpha: true });
const elBadge = $("badge");
const elContacts = $("contacts");
const elClock = $("clock");
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
  fg: cssVar("--fg"),
  dim: cssVar("--dim"),
  grid: cssVar("--grid"),
  gridHi: cssVar("--grid-hi"),
  cone: cssVar("--cone"),
  sweep: cssVar("--sweep"),
  sectorIn: cssVar("--sector-in"),
  sectorOut: cssVar("--sector-out"),
  box: cssVar("--box"),
  gateDim: cssVar("--gate-dim"),
};
// index: 0 green (moving), 1 amber (still, breathing), 2 gray (not assessed)
const TRIAGE_COLORS = [cssVar("--triage-green"), cssVar("--triage-amber"), cssVar("--triage-gray")];
const FONT_LABEL = '600 18px Rajdhani, "DejaVu Sans Condensed", sans-serif';
const FONT_ID = '700 22px Rajdhani, "DejaVu Sans Condensed", sans-serif';
const ID_LABELS = ["", "1", "2", "3"];

function triageIndex(triage) {
  return triage === TRIAGE.GREEN ? 0 : triage === TRIAGE.AMBER ? 1 : 2;
}

// ---- state ----

function makeTrack(id) {
  return {
    id, active: false, leaving: false, leaveAt: 0,
    fx: 0, fy: 0, tx: 0, ty: 0, t0: 0,     // from / to position (mm) and when the 'to' arrived
    x: 0, y: 0,                              // current render position (mm)
    tri: 2, locked: false, lockAt: 0,
    lastSeen: 0, seenAt: 0,
    trail: new Float32Array(TRAIL_N * 2), trailHead: 0, trailCount: 0, trailAt: 0,
    pingAt: -1e9, prevRel: NaN,
  };
}
const tracks = TARGET_IDS.map(makeTrack);
const seenFlags = new Uint8Array(TARGET_IDS.length);

let gateRange = DEFAULT_GATE.max_range_m;
let gateAngle = DEFAULT_GATE.max_angle_deg;
let lockedTrack = null;
let vHeart = null;
let vBreath = null;
let haveSnapshot = false;

let renderScale = 1;
let gridDirty = true;
let pxPerMm = RADIUS / (gateRange * 1000);

// ---- static grid layer (offscreen, redrawn only on gate / size / font change) ----

const gridCanvas = document.createElement("canvas");
const gridCtx = gridCanvas.getContext("2d");
let conePath = new Path2D();

const px = (r, deg) => APEX_X + r * Math.sin(deg * DEG);
const py = (r, deg) => APEX_Y - r * Math.cos(deg * DEG);
const cAng = (deg) => (deg - 90) * DEG;          // sector degrees (0 = up) to canvas arc angle

function sectorPath(g, r, fromDeg, toDeg) {
  g.moveTo(APEX_X, APEX_Y);
  g.arc(APEX_X, APEX_Y, r, cAng(fromDeg), cAng(toDeg));
  g.closePath();
}

function rebuildGrid() {
  gridCanvas.width = canvas.width;
  gridCanvas.height = canvas.height;
  const g = gridCtx;
  g.setTransform(renderScale, 0, 0, renderScale, 0, 0);
  g.clearRect(0, 0, W, H);
  const scaleM = RADIUS / gateRange;               // px per metre

  // sector fill
  const fill = g.createRadialGradient(APEX_X, APEX_Y, 0, APEX_X, APEX_Y, RADIUS);
  fill.addColorStop(0, C.sectorIn);
  fill.addColorStop(1, C.sectorOut);
  g.fillStyle = fill;
  g.beginPath();
  sectorPath(g, RADIUS, -FOV_DEG, FOV_DEG);
  g.fill();

  // beyond the angle gate (set_gate with a narrower max_angle_deg)
  if (gateAngle < FOV_DEG) {
    g.fillStyle = C.gateDim;
    g.beginPath();
    sectorPath(g, RADIUS, -FOV_DEG, -gateAngle);
    sectorPath(g, RADIUS, gateAngle, FOV_DEG);
    g.fill();
  }

  // lock cone: faint wedge + dashed outline; frame() brightens it while locked
  conePath = new Path2D();
  const cone = LOCK_CONE;
  const rIn = cone.minRangeM * scaleM;
  const rOut = cone.maxRangeM * scaleM;
  conePath.moveTo(px(rIn, -cone.maxAngleDeg), py(rIn, -cone.maxAngleDeg));
  conePath.lineTo(px(rOut, -cone.maxAngleDeg), py(rOut, -cone.maxAngleDeg));
  conePath.arc(APEX_X, APEX_Y, rOut, cAng(-cone.maxAngleDeg), cAng(cone.maxAngleDeg));
  conePath.lineTo(px(rIn, cone.maxAngleDeg), py(rIn, cone.maxAngleDeg));
  conePath.arc(APEX_X, APEX_Y, rIn, cAng(cone.maxAngleDeg), cAng(-cone.maxAngleDeg), true);
  conePath.closePath();
  g.globalAlpha = 0.09;
  g.fillStyle = C.cone;
  g.fill(conePath);
  g.globalAlpha = 0.55;
  g.strokeStyle = C.cone;
  g.lineWidth = 1.5;
  g.setLineDash([6, 5]);
  g.stroke(conePath);
  g.setLineDash([]);
  g.globalAlpha = 1;

  // range rings every 1 m, outer arc at the gate
  g.font = FONT_LABEL;
  g.textBaseline = "alphabetic";
  g.textAlign = "left";
  g.lineWidth = 1.5;
  for (let m = 1; m < gateRange - 0.01; m += 1) {
    const r = m * scaleM;
    g.strokeStyle = C.grid;
    g.beginPath();
    g.arc(APEX_X, APEX_Y, r, cAng(-FOV_DEG), cAng(FOV_DEG));
    g.stroke();
  }
  g.strokeStyle = C.gridHi;
  g.lineWidth = 3;
  g.beginPath();
  g.arc(APEX_X, APEX_Y, RADIUS, cAng(-FOV_DEG), cAng(FOV_DEG));
  g.stroke();
  // ring labels sit on the -45 deg spoke with a dark backing, clear of the sector edge and the 60 deg label
  g.textAlign = "center";
  g.textBaseline = "middle";
  const labelRing = (r, text) => {
    const cx = px(r, LABEL_DEG);
    const cy = py(r, LABEL_DEG);
    const w = g.measureText(text).width + 10;
    g.fillStyle = C.box;
    g.fillRect(cx - w / 2, cy - 11, w, 22);
    g.fillStyle = C.dim;
    g.fillText(text, cx, cy + 1);
  };
  for (let m = 1; m < gateRange - 0.01; m += 1) labelRing(m * scaleM, m + " m");
  labelRing(RADIUS, Number.isInteger(gateRange) ? gateRange + " m" : gateRange.toFixed(1) + " m");

  // sector edges + angle ticks every 15 deg
  g.strokeStyle = C.gridHi;
  g.lineWidth = 2;
  g.beginPath();
  g.moveTo(APEX_X, APEX_Y);
  g.lineTo(px(RADIUS, -FOV_DEG), py(RADIUS, -FOV_DEG));
  g.moveTo(APEX_X, APEX_Y);
  g.lineTo(px(RADIUS, FOV_DEG), py(RADIUS, FOV_DEG));
  g.stroke();
  g.lineWidth = 1;
  g.strokeStyle = C.grid;
  g.beginPath();
  for (const a of [-30, 0, 30]) {
    g.moveTo(APEX_X, APEX_Y);
    g.lineTo(px(RADIUS, a), py(RADIUS, a));
  }
  g.stroke();
  g.strokeStyle = C.gridHi;
  g.lineWidth = 2;
  g.beginPath();
  for (let a = -FOV_DEG; a <= FOV_DEG; a += 15) {
    const len = a % 30 === 0 ? 16 : 9;
    g.moveTo(px(RADIUS, a), py(RADIUS, a));
    g.lineTo(px(RADIUS - len, a), py(RADIUS - len, a));
  }
  g.stroke();
  g.fillStyle = C.dim;
  g.textAlign = "center";
  g.textBaseline = "middle";
  for (const a of [-60, -30, 30, 60]) {
    g.fillText(Math.abs(a) + "°", px(RADIUS + 20, a), py(RADIUS + 20, a));
  }

  // the device
  g.fillStyle = TRIAGE_COLORS[0];
  g.beginPath();
  g.moveTo(APEX_X, APEX_Y - 16);
  g.lineTo(APEX_X - 10, APEX_Y + 3);
  g.lineTo(APEX_X + 10, APEX_Y + 3);
  g.closePath();
  g.fill();
  gridDirty = false;
}

// ---- ECG-style beat trace (stylised beat at the measured rate; flat when there is no reading) ----

const BEAT = new Float32Array(160);
{
  // P, Q, R, S, T as gaussians around the R peak at phase 0: [center, height, sigma]
  const comps = [[-0.2, 0.16, 0.04], [-0.04, -0.16, 0.022], [0, 1, 0.02], [0.04, -0.28, 0.024], [0.26, 0.3, 0.06]];
  for (let i = 0; i < BEAT.length; i++) {
    const u = i / BEAT.length;
    let v = 0;
    for (const [c, h, s] of comps) {
      let d = u - c;
      d -= Math.round(d);
      v += h * Math.exp(-(d * d) / (2 * s * s));
    }
    BEAT[i] = v;
  }
}
const ecg = new Float32Array(ECG_N);
let ecgHead = 0;
let ecgPhase = 0;
let ecgAcc = 0;
let ecgLast = 0;
let lastBeatAt = -1e9;
let heartFlashOn = false;

function ecgStep(ts) {
  let v = 0;
  if (vHeart !== null) {
    ecgPhase += (vHeart / 60) * (ECG_STEP_MS / 1000);
    if (ecgPhase >= 1) {
      ecgPhase -= 1;
      lastBeatAt = ts;
    }
    v = BEAT[(ecgPhase * BEAT.length) | 0];
  } else {
    ecgPhase = 0;
  }
  ecg[ecgHead] = v;
  ecgHead = (ecgHead + 1) % ECG_N;
}

// ---- snapshots -> state ----

function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}
function setAttr(el, name, value) {
  if (el.getAttribute(name) !== value) el.setAttribute(name, value);
}
function setVital(el, value) {
  if (value === null) {
    setText(el, "settling...");
    el.classList.add("settling");
  } else {
    setText(el, String(value));
    el.classList.remove("settling");
  }
}

function applySnapshot(s, now) {
  if (s.v !== CONTRACT_VERSION) console.warn("snapshot v" + s.v + ", UI built for v" + CONTRACT_VERSION);

  // gate
  if (s.gate) {
    if (s.gate.max_range_m !== gateRange || s.gate.max_angle_deg !== gateAngle) {
      gateRange = s.gate.max_range_m;
      gateAngle = s.gate.max_angle_deg;
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
      tr.trailCount = 0;
      tr.trailAt = now;
      tr.pingAt = -1e9;
      tr.prevRel = NaN;
      tr.locked = false;
    } else {
      tr.fx = tr.x;
      tr.fy = tr.y;
      tr.tx = t.x_mm;
      tr.ty = t.y_mm;
    }
    tr.leaving = false;
    tr.t0 = now;
    tr.tri = triageIndex(t.triage);
    if (t.locked && !tr.locked) tr.lockAt = now;
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

  // vitals
  const v = s.vitals;
  const hasLock = v.target_id !== null && lockedTrack !== null;
  vHeart = hasLock ? v.heart_bpm : null;
  vBreath = hasLock ? v.breath_rpm : null;
  setAttr(elVitals, "data-state", hasLock ? "locked" : "idle");
  if (hasLock) {
    setText(elVId, String(v.target_id));
    const tgt = s.targets.find((x) => x.id === v.target_id);
    setText(elVRange, tgt ? tgt.range_m.toFixed(1) + " m" : "-");
    setVital(elHeart, vHeart);
    setVital(elBreath, vBreath);
  }

  // status bar
  setText(elBadge, s.source.toUpperCase());
  setAttr(elBadge, "data-source", s.source);
  setAttr(pillLd, "data-status", s.sensors.ld2450);
  setText(pillLdText, s.sensors.ld2450.toUpperCase());
  setAttr(pillC1, "data-status", s.sensors.c1001);
  setText(pillC1Text, s.sensors.c1001.toUpperCase());
  setText(elContacts, String(s.contacts.length));
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

const sweepDeg = (t) => -FOV_DEG * Math.cos((Math.PI * t) / SWEEP_PASS_MS);

let fpsEl = null;
let fpsFrames = 0;
let fpsSince = 0;

function drawTrack(tr, ts, sweep) {
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
  const held = tr.lastSeen > 0;

  // position: glide from the previous render position to the new snapshot
  const u = Math.min((ts - tr.t0) / INTERP_MS, 1);
  tr.x = tr.fx + (tr.tx - tr.fx) * u;
  tr.y = tr.fy + (tr.ty - tr.fy) * u;
  const sx = APEX_X + tr.x * pxPerMm;
  const sy = APEX_Y - tr.y * pxPerMm;
  const color = TRIAGE_COLORS[tr.tri];

  // trail samples
  if (ts - tr.trailAt >= TRAIL_MS) {
    tr.trailAt = ts;
    tr.trail[tr.trailHead * 2] = tr.x;
    tr.trail[tr.trailHead * 2 + 1] = tr.y;
    tr.trailHead = (tr.trailHead + 1) % TRAIL_N;
    if (tr.trailCount < TRAIL_N) tr.trailCount++;
  }

  // ping when the sweep crosses the dot
  const ang = Math.atan2(tr.x, tr.y) / DEG;
  const rel = sweep - ang;
  if (!held && tr.prevRel === tr.prevRel && (tr.prevRel <= 0) !== (rel <= 0)) tr.pingAt = ts;
  tr.prevRel = rel;

  // trail
  if (!held) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 4;
    ctx.lineCap = "round";
    let lx = sx;
    let ly = sy;
    for (let j = 0; j < tr.trailCount; j++) {
      const idx = (tr.trailHead - 1 - j + TRAIL_N * 2) % TRAIL_N;
      const tx = APEX_X + tr.trail[idx * 2] * pxPerMm;
      const ty = APEX_Y - tr.trail[idx * 2 + 1] * pxPerMm;
      ctx.globalAlpha = 0.5 * alpha * (1 - j / TRAIL_N);
      ctx.beginPath();
      ctx.moveTo(lx, ly);
      ctx.lineTo(tx, ty);
      ctx.stroke();
      lx = tx;
      ly = ty;
    }
  }

  // ping ring
  const pingAge = ts - tr.pingAt;
  if (pingAge < PING_MS) {
    const e = pingAge / PING_MS;
    ctx.globalAlpha = 0.85 * (1 - e) * alpha;
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(sx, sy, 10 + 34 * e, 0, Math.PI * 2);
    ctx.stroke();
  }

  // dot: glow, core (hollow ring while held), id
  let glow = 24;
  if (tr.locked) {
    const beatAge = ts - lastBeatAt;
    if (beatAge < 260) glow += 12 * (1 - beatAge / 260);
  }
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.18 * alpha;
  ctx.beginPath();
  ctx.arc(sx, sy, glow, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = alpha;
  if (held) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.arc(sx, sy, 11, 0, Math.PI * 2);
    ctx.stroke();
  } else {
    ctx.beginPath();
    ctx.arc(sx, sy, 12, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.font = FONT_ID;
  ctx.textBaseline = "alphabetic";
  if (tr.locked) {
    // beside the reticle, on the side away from the trace box
    const traceRight = sx + 40 + ECG_W <= W - 6;
    ctx.textAlign = traceRight ? "right" : "left";
    ctx.fillText(ID_LABELS[tr.id], traceRight ? sx - 40 : sx + 40, sy + 8);
  } else {
    ctx.textAlign = "left";
    ctx.fillText(ID_LABELS[tr.id], sx + 17, sy - 13);
  }
}

function drawLock(tr, ts) {
  const sx = APEX_X + tr.x * pxPerMm;
  const sy = APEX_Y - tr.y * pxPerMm;
  const age = ts - tr.lockAt;
  let d = 30 + 1.5 * Math.sin(ts / 220);
  if (age < 250) {
    const k = 1 - age / 250;
    d += 18 * k * k;
  }
  const arm = 9;
  ctx.globalAlpha = 1;
  ctx.strokeStyle = tr.tri === 1 ? TRIAGE_COLORS[1] : C.fg;
  ctx.lineWidth = 3;
  ctx.lineCap = "butt";
  ctx.beginPath();
  for (let ix = -1; ix <= 1; ix += 2) {
    for (let iy = -1; iy <= 1; iy += 2) {
      ctx.moveTo(sx + ix * d, sy + iy * (d - arm));
      ctx.lineTo(sx + ix * d, sy + iy * d);
      ctx.lineTo(sx + ix * (d - arm), sy + iy * d);
    }
  }
  ctx.stroke();

  // beat trace beside the reticle, flipped left near the right edge
  let bx = sx + 40;
  if (bx + ECG_W > W - 6) bx = sx - 40 - ECG_W;
  let by = sy - ECG_H / 2;
  if (by < 42) by = 42;
  if (by > H - ECG_H - 4) by = H - ECG_H - 4;
  ctx.fillStyle = C.box;
  ctx.fillRect(bx - 3, by - 3, ECG_W + 6, ECG_H + 6);
  const mid = by + ECG_H / 2;
  const amp = ECG_H / 2 - 3;
  const live = vHeart !== null;
  ctx.strokeStyle = live ? TRIAGE_COLORS[1] : TRIAGE_COLORS[2];
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  const half = ECG_N / 2;
  for (let pass = 0; pass < 2; pass++) {
    ctx.globalAlpha = pass === 0 ? 0.4 : 1;
    ctx.beginPath();
    const from = pass === 0 ? 0 : half - 1;
    const to = pass === 0 ? half : ECG_N;
    for (let i = from; i < to; i++) {
      const v = ecg[(ecgHead + i) % ECG_N];
      const x = bx + (i / ECG_N) * ECG_W;
      const y = mid - v * amp;
      if (i === from) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function frame(ts) {
  requestAnimationFrame(frame);
  if (gridDirty) rebuildGrid();

  ctx.clearRect(0, 0, W, H);
  ctx.globalAlpha = 1;
  ctx.drawImage(gridCanvas, 0, 0, W, H);

  // lock cone brightens while a lock is held
  const locked = lockedTrack !== null && lockedTrack.active;
  if (locked) {
    ctx.fillStyle = C.cone;
    ctx.strokeStyle = C.cone;
    ctx.globalAlpha = 0.12 + 0.05 * Math.sin(ts / 260);
    ctx.fill(conePath);
    ctx.globalAlpha = 0.9;
    ctx.lineWidth = 2;
    ctx.stroke(conePath);
  }

  // sweep: fading wedge trail (sampled back in time, so it follows the turnarounds) + line
  const sweep = sweepDeg(ts);
  ctx.fillStyle = C.sweep;
  let pxPrev = px(RADIUS, sweep);
  let pyPrev = py(RADIUS, sweep);
  for (let k = 1; k <= TRAIL_SLICES; k++) {
    const a = sweepDeg(ts - k * TRAIL_SLICE_MS);
    const x = px(RADIUS, a);
    const y = py(RADIUS, a);
    const f = 1 - (k - 1) / TRAIL_SLICES;
    ctx.globalAlpha = 0.22 * f * f;
    ctx.beginPath();
    ctx.moveTo(APEX_X, APEX_Y);
    ctx.lineTo(pxPrev, pyPrev);
    ctx.lineTo(x, y);
    ctx.fill();
    pxPrev = x;
    pyPrev = y;
  }
  ctx.strokeStyle = C.sweep;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(APEX_X, APEX_Y);
  ctx.lineTo(px(RADIUS, sweep), py(RADIUS, sweep));
  ctx.globalAlpha = 0.25;
  ctx.lineWidth = 8;
  ctx.stroke();
  ctx.globalAlpha = 0.95;
  ctx.lineWidth = 2.5;
  ctx.stroke();

  // targets
  for (let i = 0; i < tracks.length; i++) {
    if (tracks[i].active) drawTrack(tracks[i], ts, sweep);
  }
  ctx.globalAlpha = 1;

  // lock reticle + trace; the trace advances in fixed steps regardless of frame rate
  if (locked) {
    if (ecgLast === 0) ecgLast = ts;
    ecgAcc += Math.min(ts - ecgLast, 100);
    ecgLast = ts;
    while (ecgAcc >= ECG_STEP_MS) {
      ecgAcc -= ECG_STEP_MS;
      ecgStep(ts);
    }
    drawLock(lockedTrack, ts);
  } else {
    ecgLast = 0;
    ecgAcc = 0;
  }

  // heart number pulses on each beat
  const flash = vHeart !== null && ts - lastBeatAt < 140;
  if (flash !== heartFlashOn) {
    heartFlashOn = flash;
    elHeart.classList.toggle("beat", flash);
  }

  if (fpsEl) {
    fpsFrames++;
    if (ts - fpsSince >= 1000) {
      fpsEl.textContent = fpsFrames + " fps";
      fpsFrames = 0;
      fpsSince = ts;
    }
  }
}

// ---- sizing, kiosk guards, clock, boot ----

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

function tickClock() {
  setText(elClock, new Date().toTimeString().slice(0, 8));
}
tickClock();
setInterval(tickClock, 1000);

if (new URLSearchParams(location.search).get("fps") === "1") {
  fpsEl = document.createElement("div");
  fpsEl.id = "fps";
  stage.appendChild(fpsEl);
}

fit();
showNoSignal(true, "Connecting...");
connect();
requestAnimationFrame(frame);

// canvas text must wait for the bundled font, then the grid is redrawn with it
if (document.fonts && document.fonts.load) {
  Promise.all([
    document.fonts.load('600 18px "Rajdhani"'),
    document.fonts.load('700 22px "Rajdhani"'),
  ]).then(() => { gridDirty = true; }, () => { /* fallback font is fine */ });
}
