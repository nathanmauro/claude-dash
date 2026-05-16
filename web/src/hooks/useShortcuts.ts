import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { shiftDate } from "../utils/format";

interface ShortcutsOpts {
  filterRef?: React.RefObject<HTMLInputElement | null>;
  onClearFilter?: () => void;
}

export function useShortcuts(opts: ShortcutsOpts = {}) {
  const { filterRef, onClearFilter } = opts;
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) {
        if (e.key === "Escape" && filterRef?.current && t === filterRef.current) {
          onClearFilter?.();
          filterRef.current.blur();
        }
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const from = params.get("from") ?? undefined;
      const to = params.get("to") ?? undefined;
      const date = params.get("date") ?? undefined;

      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        const days = e.key === "ArrowLeft" ? -1 : 1;
        const next = new URLSearchParams(params);
        if (date) {
          next.set("date", shiftDate(date, days));
        } else if (from && to) {
          next.set("from", shiftDate(from, days));
          next.set("to", shiftDate(to, days));
        } else {
          const today = new Date().toISOString().slice(0, 10);
          next.set("date", shiftDate(today, days));
        }
        setParams(next);
      } else if (e.key === "t") {
        nav("/");
      } else if (e.key === "/") {
        e.preventDefault();
        filterRef?.current?.focus();
      }
    }

    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [params, setParams, nav, filterRef, onClearFilter]);
}
