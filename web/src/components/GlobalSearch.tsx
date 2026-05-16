import { useEffect, useState } from "react";
import { useSearch } from "../hooks/useSearch";
import "../styles/components/search.css";

interface Props {
  query: string;
  onPick: (sid: string) => void;
}

export function GlobalSearch({ query, onPick }: Props) {
  const { data, isFetching } = useSearch(query);
  const [active, setActive] = useState(0);

  useEffect(() => {
    setActive(0);
  }, [query]);

  useEffect(() => {
    if (!data || data.length === 0) return;
    const hits = data;
    function onKey(e: KeyboardEvent) {
      if (document.activeElement?.tagName !== "INPUT") return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((a) => Math.min(hits.length - 1, a + 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((a) => Math.max(0, a - 1));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const hit = hits[active];
        if (hit) onPick(hit.session_id);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [data, active, onPick]);

  if (query.trim().length < 3) return null;
  if (isFetching && !data) {
    return (
      <div className="search-results">
        <div className="search-header">Searching…</div>
      </div>
    );
  }
  if (!data || data.length === 0) return null;

  return (
    <div className="search-results">
      <div className="search-header">
        <span>Global Search · {data.length} hit{data.length === 1 ? "" : "s"}</span>
        <span className="hint">↑↓ navigate · ↵ jump</span>
      </div>
      {data.map((r, i) => (
        <button
          key={r.session_id}
          className={`search-hit ${i === active ? "active" : ""}`}
          type="button"
          onMouseEnter={() => setActive(i)}
          onClick={() => onPick(r.session_id)}
        >
          <div className="hit-meta">
            {r.date} · {r.cwd.split("/").pop()}
          </div>
          <div className="hit-title">{r.title}</div>
          <div
            className="hit-snippet"
            dangerouslySetInnerHTML={{ __html: r.snippet }}
          />
        </button>
      ))}
    </div>
  );
}
