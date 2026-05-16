import { api } from "../api";
import { showToast } from "../hooks/useToast";
import { homeCollapse } from "../utils/format";
import "../styles/components/icon-row.css";

interface Props {
  cwd: string;
  projectName: string;
  githubUrl?: string | null;
  augmentStatus?: string;
}

async function fire(label: string, p: Promise<{ ok: boolean; message?: string }>) {
  try {
    const r = await p;
    if (r.ok) {
      if (r.message && r.message !== "ok" && !r.message.startsWith("/")) {
        showToast(`${label}: ${r.message}`, "ok");
      }
    } else {
      showToast(`${label}: ${r.message ?? "failed"}`, "err");
    }
  } catch (e) {
    showToast(`${label}: ${(e as Error).message}`, "err");
  }
}

export function IconRow({ cwd, projectName, githubUrl, augmentStatus }: Props) {
  const isIndexed = augmentStatus === "indexed" || augmentStatus?.startsWith("indexed at");
  const notionUrl = `https://www.notion.so/search?q=${encodeURIComponent(projectName)}`;

  return (
    <div className="icon-row" onClick={(e) => e.stopPropagation()}>
      <button
        className="icon-btn"
        type="button"
        onClick={() => fire("Finder", api.openFinder(cwd))}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z" />
        </svg>
        <span className="tooltip">Finder: {homeCollapse(cwd)}</span>
      </button>

      <button
        className="icon-btn"
        type="button"
        onClick={() => fire("Terminal", api.openTerminal(cwd))}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="4 17 10 11 4 5" />
          <line x1="12" y1="19" x2="20" y2="19" />
        </svg>
        <span className="tooltip">Terminal</span>
      </button>

      <button
        className="icon-btn"
        type="button"
        onClick={() => fire("Editor", api.openEditor(cwd))}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
        </svg>
        <span className="tooltip">Editor (Cursor)</span>
      </button>

      {githubUrl && (
        <a className="icon-btn" href={githubUrl} target="_blank" rel="noreferrer">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22" />
          </svg>
          <span className="tooltip">GitHub: {githubUrl.split("/").pop()}</span>
        </a>
      )}

      <a className="icon-btn" href={notionUrl} target="_blank" rel="noreferrer">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="9" y1="15" x2="15" y2="15" />
          <line x1="9" y1="11" x2="15" y2="11" />
          <line x1="9" y1="19" x2="13" y2="19" />
        </svg>
        <span className="tooltip">Notion Project</span>
      </a>

      <button
        className={`icon-btn ${isIndexed ? "ok" : ""}`}
        type="button"
        onClick={() => fire("Augment index", api.augmentIndex(cwd))}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z" />
          <path d="M12 6v6l4 2" />
        </svg>
        <span className="tooltip">Augment: {augmentStatus ?? "not indexed"} (Click to index)</span>
      </button>
    </div>
  );
}
