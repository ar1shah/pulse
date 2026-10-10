// Range buttons (2 / 4 / 6 m) and the wordmark long-press that clears the contact log.
// The active range button comes only from the snapshot's gate, never from what was tapped.
import { setText, setAttr } from "./fmt.js";

const HOLD_MS = 1500;
const TOAST_MS = 1800;

const $ = (id) => document.getElementById(id);
const buttons = [...document.querySelectorAll("#ranges .range")];
const wordmark = $("wordmark");
const toast = $("toast");

let holdTimer = 0;
let toastTimer = 0;

function showToast(text) {
  setText(toast, text);
  setAttr(toast, "data-show", "1");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => setAttr(toast, "data-show", "0"), TOAST_MS);
}

function cancelHold() {
  clearTimeout(holdTimer);
  holdTimer = 0;
  wordmark.classList.remove("holding");
}

export function initControls({ send, onReset }) {
  for (const b of buttons) {
    b.addEventListener("click", () => send({ type: "set_gate", max_range_m: Number(b.dataset.range) }));
  }

  wordmark.addEventListener("pointerdown", () => {
    cancelHold();
    wordmark.classList.add("holding");
    holdTimer = setTimeout(() => {
      cancelHold();
      send({ type: "reset_contacts" });
      onReset();
      showToast("Contacts cleared");
    }, HOLD_MS);
  });
  for (const type of ["pointerup", "pointercancel", "pointerleave"]) wordmark.addEventListener(type, cancelHold);
}

export function controlsUpdate(s) {
  for (const b of buttons) {
    const on = Math.abs(s.gate.max_range_m - Number(b.dataset.range)) < 0.05;
    setAttr(b, "aria-pressed", on ? "true" : "false");
  }
}
