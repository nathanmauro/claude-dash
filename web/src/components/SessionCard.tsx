import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { ProjectInfo, SessionData } from "../api";
import { api } from "../api";
import { showToast } from "../hooks/useToast";
import { fmtDuration, fmtRange, fmtTokens, pluralS, truncate } from "../utils/format";
import { IconRow } from "./IconRow";
import "../styles/components/session.css";

interface Props {
  session: SessionData;
  project?: ProjectInfo;
  expandRequest?: number;
}

const STATUS_LABEL: Record<string, string> = {
  completed: "done",
  in_progress: "in-prog",
  pending: "todo",
};

function loadOpen(sid: string, defaultOpen: boolean): boolean {
  try {
    const v = localStorage.getItem(`session:${sid}`);
    if (v === "1") return true;
    if (v === "0") return false;
  } catch {}
  return defaultOpen;
}

export function SessionCard({ session, project, expandRequest }: Props) {
  const incomplete = session.incomplete_count;
  const completed = session.completed_count;
  const defaultOpen = incomplete > 0;
  const [open, setOpen] = useState(() => loadOpen(session.session_id, defaultOpen));
  const [copied, setCopied] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const elRef = useRef<HTMLElement>(null);
  const qc = useQueryClient();

  useEffect(() => {
    if (!expandRequest) return;
    setOpen(true);
    elRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [expandRequest]);

  function toggle() {
    const next = !open;
    setOpen(next);
    try {
      localStorage.setItem(`session:${session.session_id}`, next ? "1" : "0");
    } catch {}
  }

  async function copySid(e: React.MouseEvent) {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(session.session_id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1000);
    } catch {}
  }

  async function onResume(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const r = await api.resume(session.session_id, session.cwd, prompt);
      if (r.ok) {
        showToast("✓ launched in Terminal", "ok");
        setPrompt("");
        qc.invalidateQueries({ queryKey: ["dashboard"] });
      } else {
        showToast(`resume failed: ${r.message ?? ""}`, "err");
      }
    } catch (err) {
      showToast(`resume failed: ${(err as Error).message}`, "err");
    } finally {
      setSubmitting(false);
    }
  }

  const tasks = Object.values(session.tasks);
  const title = session.title || session.first_prompt.slice(0, 80) || session.session_id;
  const firstPrompt = session.first_prompt
    ? truncate(session.first_prompt, 220)
    : null;
  const lastPrompt =
    session.last_prompt && session.last_prompt !== session.first_prompt
      ? truncate(session.last_prompt, 220)
      : null;

  return (
    <article
      ref={elRef}
      className={`session ${incomplete ? "warn" : ""} ${open ? "" : "closed"}`}
      id={`sid-${session.session_id}`}
    >
      <button type="button" className="session-summary" onClick={toggle}>
        <div className="meta">
          <span className="time">{fmtRange(session.start_ts, session.end_ts)}</span>
          <span className="duration">{fmtDuration(session.start_ts, session.end_ts)}</span>
          <span className="msgs">
            {session.user_msg_count} msg{pluralS(session.user_msg_count)}
          </span>
          {session.billable_tokens > 0 && (
            <span className="tokens">{fmtTokens(session.billable_tokens)} tok</span>
          )}
          {incomplete > 0 ? (
            <span className="pill warn">
              {incomplete} open task{pluralS(incomplete)}
            </span>
          ) : tasks.length > 0 ? (
            <span className="pill ok">{completed} done</span>
          ) : null}
        </div>
        <div className="session-title-row">
          <h3>{title}</h3>
          <IconRow
            cwd={session.cwd}
            projectName={project?.name ?? session.cwd.split("/").pop() ?? ""}
            githubUrl={project?.github_url}
            augmentStatus={project?.augment_status}
          />
        </div>
        <span
          className={`sid ${copied ? "copied" : ""}`}
          title="click to copy"
          onClick={copySid}
          role="button"
        >
          {session.session_id}
        </span>
      </button>
      {open && (
        <div className="session-body">
          <section className="prompts">
            <div className="prompt-row">
              <span className="lbl">first</span>{" "}
              {firstPrompt ?? <span className="muted">(no user prompt)</span>}
            </div>
            {lastPrompt && (
              <div className="prompt-row">
                <span className="lbl">last</span> {lastPrompt}
              </div>
            )}
          </section>
          <section>
            {tasks.length === 0 ? (
              <p className="muted">No tracked tasks.</p>
            ) : (
              <ul className="tasks">
                {tasks.map((t) => (
                  <li key={t.task_id}>
                    <span className={`status ${t.status}`}>
                      {STATUS_LABEL[t.status] ?? t.status}
                    </span>
                    <span className="subject">{t.subject}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <form className="resume" onSubmit={onResume}>
            <input
              className="prompt-input"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Optional direction for resumed session…"
              autoComplete="off"
            />
            <button type="submit" disabled={submitting}>
              Resume ↻
            </button>
          </form>
        </div>
      )}
    </article>
  );
}
