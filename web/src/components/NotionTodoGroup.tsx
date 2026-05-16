import { useState } from "react";
import type { NotionTodo } from "../api";
import { NotionTodoItem } from "./NotionTodoItem";

interface Props {
  name: string;
  todos: NotionTodo[];
  projectIndex: Record<string, [string, string]>;
  knownSids: Set<string>;
}

function loadOpen(name: string, defaultOpen: boolean): boolean {
  try {
    const v = localStorage.getItem(`todo-group:${name}`);
    if (v === "1") return true;
    if (v === "0") return false;
  } catch {}
  return defaultOpen;
}

export function NotionTodoGroup({ name, todos, projectIndex, knownSids }: Props) {
  const [open, setOpen] = useState(() => loadOpen(name, true));

  function toggle() {
    const next = !open;
    setOpen(next);
    try {
      localStorage.setItem(`todo-group:${name}`, next ? "1" : "0");
    } catch {}
  }

  return (
    <div className={`todo-group ${open ? "open" : ""}`}>
      <button type="button" className="todo-group-summary" onClick={toggle}>
        <span className="proj-name">{name}</span>
        <span className="proj-count">{todos.length}</span>
      </button>
      {open && (
        <ul className="todos">
          {todos.map((t, i) => (
            <NotionTodoItem
              key={`${t.url ?? t.name}-${i}`}
              todo={t}
              match={projectIndex[t.project?.trim().toLowerCase() ?? ""]}
              knownSids={knownSids}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
