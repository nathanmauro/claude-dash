import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { NotionTodo } from "../api";
import { api } from "../api";
import { showToast } from "../hooks/useToast";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function pad2(n: number) {
  return n.toString().padStart(2, "0");
}

function classifyDue(due: string | null): { cls: string; label: string } {
  if (!due) return { cls: "", label: "" };
  const d = new Date(due.slice(0, 10) + "T00:00:00");
  if (Number.isNaN(d.getTime())) return { cls: "", label: due };
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  let cls = "";
  if (d < today) cls = "overdue";
  else if (d.getTime() === today.getTime()) cls = "today";
  return { cls, label: `${MONTHS[d.getMonth()]} ${pad2(d.getDate())}` };
}

interface Props {
  todo: NotionTodo;
  match?: [string, string]; // [cwd, latest_sid]
  knownSids: Set<string>;
}

export function NotionTodoItem({ todo, match, knownSids }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const { cls, label } = classifyDue(todo.due);
  const statusCls = todo.status.toLowerCase() === "in progress" ? "inprog" : "todo";
  const cwd = match?.[0];
  const latestSid = match?.[1];
  const cwdName = cwd ? cwd.split("/").filter(Boolean).pop() ?? cwd : "";
  const source = todo.source?.trim();
  const sourceIsKnown = source && knownSids.has(source);

  async function doStart() {
    if (!cwd) return;
    setBusy(true);
    try {
      const r = await api.start(cwd, todo.name);
      showToast(r.ok ? `✓ launched in Terminal` : `start failed: ${r.message ?? ""}`, r.ok ? "ok" : "err");
      if (r.ok) qc.invalidateQueries({ queryKey: ["dashboard"] });
    } catch (e) {
      showToast(`start failed: ${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  }
  async function doResume() {
    if (!cwd || !latestSid) return;
    setBusy(true);
    try {
      const r = await api.resume(latestSid, cwd, todo.name);
      showToast(r.ok ? `✓ resumed in Terminal` : `resume failed: ${r.message ?? ""}`, r.ok ? "ok" : "err");
      if (r.ok) qc.invalidateQueries({ queryKey: ["dashboard"] });
    } catch (e) {
      showToast(`resume failed: ${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className={`todo ${cls}`}>
      <button className="todo-row" type="button" onClick={() => setOpen((o) => !o)}>
        <span className={`todo-status ${statusCls}`} />
        <span className="todo-name">{todo.name || "(untitled)"}</span>
        {label && <span className="todo-due">{label}</span>}
      </button>
      {open && (
        <div className="todo-body">
          {sourceIsKnown ? (
            <a className="todo-source" href={`#sid-${source}`}>
              from {source!.slice(0, 8)}
            </a>
          ) : source ? (
            <span className="todo-source">via {source}</span>
          ) : null}
          {cwd && (
            <button className="todo-action" type="button" onClick={doStart} disabled={busy}>
              ▶ start in {cwdName}
            </button>
          )}
          {cwd && latestSid && (
            <button className="todo-action" type="button" onClick={doResume} disabled={busy}>
              ↻ resume latest
            </button>
          )}
          {todo.url && (
            <a className="todo-open" href={todo.url} target="_blank" rel="noreferrer">
              open in notion ↗
            </a>
          )}
        </div>
      )}
    </li>
  );
}
