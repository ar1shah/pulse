// Range buttons (2 / 4 / 6 m), the wordmark long-press that clears the contact log, and the EXIT long-press that
// closes the kiosk back to the Pi desktop (shown only when the server says a kiosk is running).
// The active range button comes only from the snapshot's gate, never from what was tapped.
import { setText, setAttr } from "./fmt.js";

const HOLD_MS = 1500;
const TOAST_MS = 1800;

const $ = (id) => document.getElementById(id);
const buttons = [...document.querySelectorAll("#ranges .range")];
const wordmark = $("wordmark");
const exitBtn = $("btn-exit");
const toast = $("toast");

let toastTimer = 0;

function showToast(text) {
  setText(toast, text);
  setAttr(toast, "data-show", "1");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => setAttr(toast, "data-show", "0"), TOAST_MS);
}

// Run action after a 1.5 s press; lifting early does nothing (onShort, if given, runs instead).
function onHold(el, action, onShort) {
  let timer = 0;
  const cancel = () => {
    const wasHolding = timer !== 0;
    clearTimeout(timer);
    timer = 0;
    el.classList.remove("holding");
    return wasHolding;
  };
  el.addEventListener("pointerdown", () => {
    cancel();
    el.classList.add("holding");
    timer = setTimeout(() => { timer = 0; el.classList.remove("holding"); action(); }, HOLD_MS);
  });
  el.addEventListener("pointerup", () => { if (cancel() && onShort) onShort(); });
  for (const type of ["pointercancel", "pointerleave"]) el.addEventListener(type, cancel);
}

async function exitKiosk() {
  showToast("Closing Pulse...");
  try {
    const r = await fetch("/api/kiosk/exit", { method: "POST" });
    if (!(await r.json()).ok) showToast("No kiosk to close");
  } catch {
    showToast("Couldn't reach the server");
  }
}

export function initControls({ send, onReset }) {
  for (const b of buttons) {
    b.addEventListener("click", () => send({ type: "set_gate", max_range_m: Number(b.dataset.range) }));
  }

  onHold(wordmark, () => {
    send({ type: "reset_contacts" });
    onReset();
    showToast("Contacts cleared");
  });

  onHold(exitBtn, exitKiosk, () => showToast("Hold EXIT to close Pulse"));
  fetch("/api/kiosk")
    .then((r) => r.json())
    .then((k) => { exitBtn.hidden = !k.running; })
    .catch(() => {});
}

export function controlsUpdate(s) {
  for (const b of buttons) {
    const on = Math.abs(s.gate.max_range_m - Number(b.dataset.range)) < 0.05;
    setAttr(b, "aria-pressed", on ? "true" : "false");
  }
}
