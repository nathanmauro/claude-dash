import { useMemo, useRef, useState } from "react";
import { useDashboard } from "../hooks/useDashboard";
import { useShortcuts } from "../hooks/useShortcuts";
import { useSearchParams } from "react-router-dom";
import { TopBar } from "../components/TopBar";
import { Sidebar } from "../components/Sidebar";
import { ProjectCard } from "../components/ProjectCard";
import { GlobalSearch } from "../components/GlobalSearch";
import { pluralS, fmtTokens } from "../utils/format";
import type { SessionData } from "../api";
import "../styles/components/content.css";

function searchBlob(s: SessionData): string {
  const tasks = Object.values(s.tasks)
    .map((t) => t.subject)
    .join(" ");
  return [s.title, s.first_prompt, s.last_prompt, s.cwd, s.session_id, tasks]
    .join(" ")
    .toLowerCase();
}

export function DashboardPage() {
  const [params] = useSearchParams();
  const q = {
    from: params.get("from") ?? undefined,
    to: params.get("to") ?? undefined,
    date: params.get("date") ?? undefined,
  };
  const { data, isLoading, error } = useDashboard(q);
  const filterRef = useRef<HTMLInputElement>(null);
  const [filter, setFilter] = useState("");
  const [expandRequests, setExpandRequests] = useState<Record<string, number>>({});

  useShortcuts({ filterRef, onClearFilter: () => setFilter("") });

  const ql = filter.trim().toLowerCase();
  const sessions = data?.sessions ?? [];

  const projectsByCwd = data?.projects ?? {};
  const knownSidsSet = useMemo(
    () => new Set(data?.known_sids ?? []),
    [data?.known_sids],
  );

  const grouped = useMemo(() => {
    const m = new Map<string, SessionData[]>();
    for (const s of sessions) {
      if (ql && !searchBlob(s).includes(ql)) continue;
      const arr = m.get(s.cwd) ?? [];
      arr.push(s);
      m.set(s.cwd, arr);
    }
    return [...m.entries()]
      .map(([cwd, group]) => {
        const project = projectsByCwd[cwd];
        const sorted = group.slice().sort((a, b) => {
          const ao = a.incomplete_count > 0 ? 0 : 1;
          const bo = b.incomplete_count > 0 ? 0 : 1;
          if (ao !== bo) return ao - bo;
          return (
            new Date(b.end_ts ?? 0).getTime() - new Date(a.end_ts ?? 0).getTime()
          );
        });
        const openCount = sorted.reduce((n, s) => n + s.incomplete_count, 0);
        return { cwd, project, sessions: sorted, openCount };
      })
      .sort((a, b) => b.openCount - a.openCount);
  }, [sessions, ql, projectsByCwd]);

  const totalOpen = data?.total_open ?? 0;
  const visibleCount = grouped.reduce((n, g) => n + g.sessions.length, 0);

  function expandSession(sid: string) {
    setExpandRequests((r) => ({ ...r, [sid]: (r[sid] ?? 0) + 1 }));
  }

  return (
    <>
      <TopBar data={data} />
      <main>
        <Sidebar
          projectIndex={data?.project_index ?? {}}
          knownSids={knownSidsSet}
        />
        <section className="content">
          <div className="content-head">
            <p className="summary">
              <span className="count">{visibleCount}</span> session
              {pluralS(visibleCount)} ·{" "}
              <span className="range">{data?.range_label ?? "…"}</span>
              {totalOpen > 0 && (
                <>
                  {" · "}
                  <strong className="open-count">
                    {totalOpen} open task{pluralS(totalOpen)}
                  </strong>
                </>
              )}
              {data && data.range_usage.billable > 0 && (
                <> · {fmtTokens(data.range_usage.billable)} tokens</>
              )}
            </p>
            <div className="filter-wrap">
              <input
                ref={filterRef}
                className="filter"
                placeholder="Filter sessions…  /  to focus"
                autoComplete="off"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
            </div>
          </div>
          <GlobalSearch query={filter} onPick={expandSession} />
          {isLoading && <p className="muted">Loading…</p>}
          {error && <p className="muted">Failed to load: {(error as Error).message}</p>}
          {!isLoading && grouped.length === 0 && (
            <div className="empty">
              <div className="empty-mark">∅</div>
              <p>No sessions{ql ? ` match "${filter}"` : " in this range"}.</p>
              <p className="muted">{data?.range_label}</p>
            </div>
          )}
          {grouped.map((g) =>
            g.project ? (
              <ProjectCard
                key={g.cwd}
                project={g.project}
                sessions={g.sessions}
                expandRequests={expandRequests}
              />
            ) : null,
          )}
        </section>
      </main>
    </>
  );
}
