import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

export function useLiveIndex() {
  const qc = useQueryClient();
  useEffect(() => {
    let stopped = false;
    let es: EventSource | null = null;

    const open = () => {
      if (stopped) return;
      es = new EventSource("/api/events");
      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data?.type === "indexed") {
            qc.invalidateQueries({ queryKey: ["dashboard"] });
          }
        } catch {
          // ignore keepalive lines
        }
      };
      es.onerror = () => {
        es?.close();
        es = null;
        if (!stopped) setTimeout(open, 3_000);
      };
    };

    open();
    return () => {
      stopped = true;
      es?.close();
    };
  }, [qc]);
}
