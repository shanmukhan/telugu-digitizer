export type EditableTextElement = HTMLInputElement | HTMLTextAreaElement;

const ALLOWED_INPUT_TYPES = new Set(["", "text", "search"]);

export function isEditableTextElement(node: unknown): node is EditableTextElement {
  if (!node || typeof node !== "object") return false;
  if (node instanceof HTMLTextAreaElement) {
    return !node.disabled && !node.readOnly && !node.dataset.teluguKbdIgnore;
  }
  if (node instanceof HTMLInputElement) {
    const t = (node.type || "").toLowerCase();
    return ALLOWED_INPUT_TYPES.has(t) && !node.disabled && !node.readOnly && !node.dataset.teluguKbdIgnore;
  }
  return false;
}

function setNativeReactValue(el: EditableTextElement, nextValue: string): void {
  const proto =
    el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
  if (descriptor && typeof descriptor.set === "function") {
    descriptor.set.call(el, nextValue);
  } else {
    el.value = nextValue;
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

export function insertTextAtCursor(el: EditableTextElement, text: string): boolean {
  if (!el.isConnected) return false;
  const value = el.value ?? "";
  const start = el.selectionStart ?? value.length;
  const end = el.selectionEnd ?? value.length;
  const nextValue = value.slice(0, start) + text + value.slice(end);
  const nextCaret = start + text.length;

  setNativeReactValue(el, nextValue);
  el.focus({ preventScroll: true });
  if (typeof el.setSelectionRange === "function") {
    el.setSelectionRange(nextCaret, nextCaret);
    if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(() => {
        if (el.isConnected && document.activeElement === el) {
          el.setSelectionRange(nextCaret, nextCaret);
        }
      });
    }
  }
  return true;
}

export function backspaceAtCursor(el: EditableTextElement): boolean {
  if (!el.isConnected) return false;
  const value = el.value ?? "";
  const start = el.selectionStart ?? value.length;
  const end = el.selectionEnd ?? value.length;
  if (start === 0 && end === 0) return true;

  let nextValue: string;
  let nextCaret: number;
  if (end > start) {
    nextValue = value.slice(0, start) + value.slice(end);
    nextCaret = start;
  } else {
    const codePoints = Array.from(value.slice(0, start));
    codePoints.pop();
    const prefix = codePoints.join("");
    nextValue = prefix + value.slice(end);
    nextCaret = prefix.length;
  }

  setNativeReactValue(el, nextValue);
  el.focus({ preventScroll: true });
  if (typeof el.setSelectionRange === "function") {
    el.setSelectionRange(nextCaret, nextCaret);
    if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(() => {
        if (el.isConnected && document.activeElement === el) {
          el.setSelectionRange(nextCaret, nextCaret);
        }
      });
    }
  }
  return true;
}
