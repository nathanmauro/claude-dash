import { useSyncExternalStore } from "react";

export interface Toast {
  id: number;
  msg: string;
  kind: "ok" | "err";
}

let nextId = 1;
let toasts: Toast[] = [];
const listeners = new Set<() => void>();

function notify() {
  for (const l of listeners) l();
}

export function showToast(msg: string, kind: "ok" | "err" = "ok", ttl = 3_000) {
  const t: Toast = { id: nextId++, msg, kind };
  toasts = [...toasts, t];
  notify();
  setTimeout(() => {
    toasts = toasts.filter((x) => x.id !== t.id);
    notify();
  }, ttl);
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}
function getSnapshot() {
  return toasts;
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
