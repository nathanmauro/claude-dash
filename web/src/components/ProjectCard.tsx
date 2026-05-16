import type { ProjectInfo, SessionData } from "../api";
import { homeCollapse, pluralS } from "../utils/format";
import { IconRow } from "./IconRow";
import { SessionCard } from "./SessionCard";
import "../styles/components/project.css";

interface Props {
  project: ProjectInfo;
  sessions: SessionData[];
  expandRequests: Record<string, number>;
}

export function ProjectCard({ project, sessions, expandRequests }: Props) {
  const openCount = project.open_tasks;
  return (
    <section className="project">
      <h2 className="proj-head">
        <span className="proj-base">{project.name}</span>
        <span className="proj-path">{homeCollapse(project.cwd)}</span>
        <span className="proj-meta">
          {sessions.length} session{pluralS(sessions.length)}
          {openCount > 0 && (
            <>
              {" · "}
              <span className="open">{openCount} open</span>
            </>
          )}
        </span>
        <IconRow
          cwd={project.cwd}
          projectName={project.name}
          githubUrl={project.github_url}
          augmentStatus={project.augment_status}
        />
      </h2>
      {sessions.map((s) => (
        <SessionCard
          key={s.session_id}
          session={s}
          project={project}
          expandRequest={expandRequests[s.session_id]}
        />
      ))}
    </section>
  );
}
