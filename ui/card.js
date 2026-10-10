// Contact card: the selection (UI-only, never sent to the server) and the side panel for the selected contact.
// The card follows a target id. It also remembers that contact's first_seen, so if the id comes back as a
// different person (ids are reused) the card reads SIGNAL LOST instead of silently showing someone else.
import { TRIAGE_LABELS, LOCK_CONE } from "./contract.js";
import { setText, setAttr, setVital, bearing, ago } from "./fmt.js";

const LOST_CLOSE_MS = 3000;
const SIDE_BAND = [370, 430];       // stage x: inside this band the card keeps its side, so it never flaps

const $ = (id) => document.getElementById(id);
const stage = $("stage");
const el = {
  card: $("card"), title: $("c-title"), close: $("c-close"),
  range: $("c-range"), bearing: $("c-bearing"), motion: $("c-motion"), status: $("c-status"),
  seen: $("c-seen"), held: $("c-held"), heart: $("c-heart"), breath: $("c-breath"),
  arrow: $("c-arrow"), guide: $("c-guide"), dist: $("c-dist"), turn: $("c-turn"),
};

let sel = null;                     // { id, firstSeen } or null
let lost = false;
let lostTimer = 0;
let side = "left";
let lastSnap = null;
let dotX = () => null;              // (id) => stage x of that dot, supplied by radar.js

export function initCard(opts) {
  dotX = opts.dotX;
  setText(el.guide, "Get within " + LOCK_CONE.maxRangeM + " m and aim at them");
  el.close.addEventListener("click", clearSelection);
}

export function selectedId() {
  return sel && !lost ? sel.id : 0;
}

// the live dot for an id is the contact with the newest last_seen (ids repeat after reuse)
export function newestContact(contacts, id) {
  let best = null;
  for (const c of contacts) {
    if (c.id === id && (best === null || c.last_seen > best.last_seen)) best = c;
  }
  return best;
}

function open(id, firstSeen) {
  clearTimeout(lostTimer);
  sel = { id, firstSeen };
  lost = false;
  const x = dotX(id);
  side = x !== null && x < 400 ? "right" : "left";
  setAttr(el.card, "data-lost", "0");
  setAttr(el.card, "data-open", "1");
  if (lastSnap) cardUpdate(lastSnap);
}

export function selectTarget(id) {
  const c = lastSnap ? newestContact(lastSnap.contacts, id) : null;
  open(id, c ? c.first_seen : null);
}

export function selectContact(contact) {
  open(contact.id, contact.first_seen);
}

export function clearSelection() {
  clearTimeout(lostTimer);
  sel = null;
  lost = false;
  setAttr(el.card, "data-open", "0");
  setAttr(stage, "data-card-vitals", "0");
}

function markLost() {
  lost = true;
  setAttr(el.card, "data-lost", "1");
  setAttr(stage, "data-card-vitals", "0");
  clearTimeout(lostTimer);
  lostTimer = setTimeout(clearSelection, LOST_CLOSE_MS);
}

function guidance(s, t) {
  const a = t.angle_deg;
  const abs = Math.abs(a);
  const r = t.range_m;
  el.arrow.style.transform = "rotate(" + a.toFixed(0) + "deg)";
  let dist;
  let turn = "";
  if (r > LOCK_CONE.maxRangeM) {
    const d = r - LOCK_CONE.maxRangeM;
    dist = d < 0.05 ? "Almost there" : d.toFixed(1) + " m to go";
  } else if (r < LOCK_CONE.minRangeM) {
    dist = "Back up " + (LOCK_CONE.minRangeM - r).toFixed(1) + " m";
  } else {
    dist = "In range";
  }
  if (abs > LOCK_CONE.maxAngleDeg) {
    turn = "Turn " + Math.round(abs) + "° " + (a < 0 ? "left" : "right") + " to aim";
  } else if (r >= LOCK_CONE.minRangeM && r <= LOCK_CONE.maxRangeM) {
    turn = s.targets.some((x) => x.locked) ? "Another contact is closer to center" : "Hold steady";
  }
  setText(el.dist, dist);
  setText(el.turn, turn);
}

export function cardUpdate(s) {
  lastSnap = s;
  if (!sel || lost) return;
  const t = s.targets.find((x) => x.id === sel.id);
  const c = newestContact(s.contacts, sel.id);
  if (!t || (c && sel.firstSeen !== null && c.first_seen !== sel.firstSeen)) {
    markLost();
    return;
  }

  // keep the card on the side away from its dot, with a dead band so it does not flap
  const x = dotX(sel.id);
  if (x !== null) {
    if (x > SIDE_BAND[1]) side = "left";
    else if (x < SIDE_BAND[0]) side = "right";
  }
  setAttr(el.card, "data-side", side);

  const locked = t.locked && s.vitals.target_id === t.id;
  setAttr(el.card, "data-mode", locked ? "locked" : "free");
  setAttr(stage, "data-card-vitals", locked ? "1" : "0");
  setText(el.title, "CONTACT " + t.id);
  setText(el.range, t.range_m.toFixed(1) + " m");
  setText(el.bearing, bearing(t.angle_deg));
  setText(el.motion, t.moving ? "MOVING" : "STILL");
  setText(el.status, TRIAGE_LABELS[t.triage]);
  setAttr(el.status, "data-triage", t.triage);
  setText(el.seen, c ? ago(s.t - c.first_seen) : "-");
  setText(el.held, t.last_seen_s > 0 ? "Not detected for " + t.last_seen_s.toFixed(1) + " s" : "");

  if (locked) {
    const amber = t.triage === "amber";
    setVital(el.heart, s.vitals.heart_bpm, amber);
    setVital(el.breath, s.vitals.breath_rpm, amber);
  } else {
    guidance(s, t);
  }
}
