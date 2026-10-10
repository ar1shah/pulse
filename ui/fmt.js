// Small DOM + text helpers shared by the UI modules. No state, no allocation beyond the strings.

export function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}

export function setAttr(el, name, value) {
  if (el.getAttribute(name) !== value) el.setAttribute(name, value);
}

// A vital shows its number, or "settling..." when the snapshot has null. Never invents a value.
export function setVital(el, value, amber) {
  if (value === null) {
    setText(el, "settling...");
    el.classList.add("settling");
  } else {
    setText(el, String(value));
    el.classList.remove("settling");
  }
  el.classList.toggle("amber", amber && value !== null);
}

// angle_deg: 0 = straight ahead, negative = left of the holder
export function bearing(deg) {
  const a = Math.round(Math.abs(deg));
  return a < 2 ? "ahead" : a + "° " + (deg < 0 ? "L" : "R");
}

export function ago(sec) {
  const s = Math.max(0, Math.round(sec));
  if (s < 2) return "just now";
  if (s < 60) return s + " s ago";
  return Math.floor(s / 60) + " min " + (s % 60) + " s ago";
}

export function vitalsText(heart, breath) {
  if (heart === null && breath === null) return "no vitals yet";
  return (heart === null ? "--" : heart) + " bpm · " + (breath === null ? "--" : breath) + " /min";
}
