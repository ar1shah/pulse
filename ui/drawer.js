// Contacts drawer: every contact seen this session (the server's `contacts`), newest first.
// Tapping a contact that is still in view selects it on the radar; old appearances are dimmed.
import { TRIAGE_LABELS, MAX_CONTACTS } from "./contract.js";
import { setText, setAttr, ago, vitalsText } from "./fmt.js";
import { newestContact, selectContact, clearSelection } from "./card.js";

const $ = (id) => document.getElementById(id);
const root = $("drawer");
const list = $("d-list");
const empty = $("d-empty");
const count = $("contact-count");

const rows = [];                    // { li, btn, id, status, vitals, seen, contact }
let isOpen = false;
let latest = null;

function makeRow() {
  const li = document.createElement("li");
  li.hidden = true;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "d-row";
  const mk = (cls, parent) => {
    const e = document.createElement("span");
    e.className = cls;
    parent.appendChild(e);
    return e;
  };
  const row = { li, btn, contact: null };
  row.id = mk("d-id", btn);
  const mid = mk("d-mid", btn);
  row.status = mk("d-status", mid);
  row.vitals = mk("d-vitals", mid);
  row.seen = mk("d-seen", btn);
  btn.addEventListener("click", () => {
    if (!row.contact) return;
    const c = row.contact;
    closeDrawer();
    selectContact(c);
  });
  li.appendChild(btn);
  list.appendChild(li);
  return row;
}

function paint(s) {
  setAttr(empty, "data-show", s.contacts.length === 0 ? "1" : "0");
  for (let i = 0; i < MAX_CONTACTS; i++) {
    const row = rows[i];
    const c = s.contacts[i];
    if (!c) {
      row.li.hidden = true;
      row.contact = null;
      continue;
    }
    row.li.hidden = false;
    row.contact = c;
    const live = s.targets.some((t) => t.id === c.id) && newestContact(s.contacts, c.id) === c;
    row.btn.disabled = !live;
    setText(row.id, "#" + c.id);
    setText(row.status, TRIAGE_LABELS[c.triage]);
    setAttr(row.status, "data-triage", c.triage);
    setText(row.vitals, vitalsText(c.last_heart_bpm, c.last_breath_rpm));
    setText(row.seen, live ? "in view" : ago(s.t - c.last_seen));
  }
}

export function drawerOpen() {
  return isOpen;
}

export function closeDrawer() {
  isOpen = false;
  setAttr(root, "data-open", "0");
}

function openDrawer() {
  clearSelection();                 // the card and the drawer share the right side
  isOpen = true;
  setAttr(root, "data-open", "1");
  if (latest) paint(latest);
}

export function initDrawer() {
  for (let i = 0; i < MAX_CONTACTS; i++) rows.push(makeRow());
  $("btn-contacts").addEventListener("click", () => (isOpen ? closeDrawer() : openDrawer()));
  $("d-close").addEventListener("click", closeDrawer);
}

export function drawerUpdate(s) {
  latest = s;
  setText(count, String(s.contacts.length));
  if (isOpen) paint(s);
}
