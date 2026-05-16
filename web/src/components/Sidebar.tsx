import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useTodos } from "../hooks/useTodos";
import { showToast } from "../hooks/useToast";
import { NotionTodoGroup } from "./NotionTodoGroup";
import "../styles/components/sidebar.css";

interface Props {
  projectIndex: Record<string, [string, string]>;
  knownSids: Set<string>;
}

export function Sidebar({ projectIndex, knownSids }: Props) {
  const { data } = useTodos();
  const [refreshing, setRefreshing] = useState(false);
  const qc = useQueryClient();

  const today = useMemo(() => {
    const t = new Date();
    t.setHours(0, 0, 0, 0);
    return t;
  }, []);

  const { groups, overdue, dueToday, total } = useMemo(() => {
    const todos = data?.todos ?? [];
    const grouped: Record<string, typeof todos> = {};
    let overdue = 0;
    let dueToday = 0;
    for (const t of todos) {
      const key = (t.project || "").trim() || "Unassigned";
      (grouped[key] ??= []).push(t);
      if (t.due) {
        const d = new Date(t.due.slice(0, 10) + "T00:00:00");
        if (!Number.isNaN(d.getTime())) {
          if (d < today) overdue++;
          else if (d.getTime() === today.getTime()) dueToday++;
        }
      }
    }
    const groupEntries = Object.entries(grouped).sort(([an, ai], [bn, bi]) => {
      const aUnassigned = an === "Unassigned" ? 1 : 0;
      const bUnassigned = bn === "Unassigned" ? 1 : 0;
      if (aUnassigned !== bUnassigned) return aUnassigned - bUnassigned;
      if (ai.length !== bi.length) return bi.length - ai.length;
      return an.toLowerCase().localeCompare(bn.toLowerCase());
    });
    return { groups: groupEntries, overdue, dueToday, total: todos.length };
  }, [data, today]);

  async function refresh() {
    setRefreshing(true);
    try {
      const r = await api.refreshNotion();
      showToast(r.ok ? "✓ Notion todos refreshed" : "refresh failed (no token?)", r.ok ? "ok" : "err");
      qc.invalidateQueries({ queryKey: ["todos"] });
    } catch (e) {
      showToast(`refresh failed: ${(e as Error).message}`, "err");
    } finally {
      setRefreshing(false);
    }
  }

  let src: React.ReactNode;
  if (!data || data.source === "none") {
    src = <span className="src none">no token</span>;
  } else if (data.source === "live") {
    src = <span className="src ok">live</span>;
  } else {
    let ts = "";
    if (data.fetched_at) {
      try {
        const d = new Date(data.fetched_at);
        ts = ` · ${["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][d.getMonth()]} ${String(d.getDate()).padStart(2,"0")} ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
      } catch {
        ts = ` · ${data.fetched_at.slice(0, 16)}`;
      }
    }
    src = <span className="src stale">cached{ts}</span>;
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <h2>Notion todos</h2>
        <div className="sidebar-meta">
          {src}
          <button className="mini" type="button" onClick={refresh} disabled={refreshing}>
            refresh
          </button>
        </div>
      </div>
      <div className="counts">
        {overdue > 0 && <span className="badge bad">{overdue} overdue</span>}
        {dueToday > 0 && <span className="badge warn">{dueToday} due today</span>}
        <span className="badge">{total} open</span>
      </div>
      <div className="todo-groups">
        {groups.length === 0 ? (
          <p className="muted">No open todos.</p>
        ) : (
          groups.map(([name, items]) => (
            <NotionTodoGroup
              key={name}
              name={name}
              todos={items}
              projectIndex={projectIndex}
              knownSids={knownSids}
            />
          ))
        )}
      </div>
      {data?.source === "none" && (
        <p className="hint">
          Add an internal-integration token:
          <br />
          <code>security add-generic-password -a notion -s todo-cli -w &lt;token&gt;</code>
        </p>
      )}
    </aside>
  );
}
