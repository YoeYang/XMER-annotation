import { useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Film,
  Headphones,
  ScanFace,
  Type,
  UserRound,
} from "lucide-react";
import { useLang } from "../LangContext";
import type { Key } from "../i18n";
import {
  buildTaskSections,
  locationOf,
  taskComplete,
  ticketId,
  MODALITY_ORDER,
} from "../core/taskFlow";
import type { Attempt, Modality, Submission, Task } from "../types";

interface Props {
  tasks: Task[];
  selected: string;
  annotator: string;
  attempts: Attempt[];
  submissions: Submission[];
  onSelect: (task: Task) => void;
  disabled: boolean;
}

const icons: Record<Modality, typeof Headphones> = {
  audio: Headphones,
  text: Type,
  face: ScanFace,
  body: UserRound,
  audiovisual: Film,
};

export default function TaskSidebar({
  tasks,
  selected,
  annotator,
  attempts,
  submissions,
  onSelect,
  disabled,
}: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [filter, setFilter] = useState<"all" | "todo">("all");
  const sections = useMemo(() => buildTaskSections(tasks), [tasks]);
  const selectedTask = tasks.find((task) => task.task_id === selected);
  const [openSections, setOpenSections] = useState<Set<Modality>>(
    () => new Set(selectedTask ? [selectedTask.modality] : []),
  );

  useEffect(() => {
    if (selectedTask)
      setOpenSections((previous) =>
        new Set(previous).add(selectedTask.modality),
      );
  }, [selectedTask?.modality]);

  const { t } = useLang();
  const done = (task: Task) =>
    taskComplete(attempts, submissions, task.task_id);
  const doneCount = tasks.filter(done).length;
  const selectedLocation = selectedTask
    ? locationOf(tasks, selectedTask.task_id)
    : null;

  return (
    <aside className={"sidebar v3-sidebar " + (collapsed ? "collapsed" : "")}>
      <div className="sidebar-heading">
        <button
          className="sidebar-collapse"
          onClick={() => setCollapsed((value) => !value)}
          aria-label={collapsed ? t("side.expand") : t("side.collapse")}
          title={collapsed ? t("side.expand") : t("side.collapse")}
        >
          {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
        </button>
        {!collapsed && (
          <>
            <h2>{t("side.title")}</h2>
          </>
        )}
      </div>

      {!collapsed && (
        <>
          <div className="overall-progress">
            <div>
              <span>{t("side.progress")}</span>
              <strong>
                {doneCount}
                <small> / {tasks.length}</small>
              </strong>
            </div>
            <progress
              aria-label={t("side.progress")}
              max={tasks.length}
              value={doneCount}
            />
          </div>

          <div className="filter-tabs" aria-label={t("side.tasks")}>
            <button
              aria-pressed={filter === "all"}
              className={filter === "all" ? "active" : ""}
              onClick={() => setFilter("all")}
            >
              {t("side.all")}
            </button>
            <button
              aria-pressed={filter === "todo"}
              className={filter === "todo" ? "active" : ""}
              onClick={() => setFilter("todo")}
            >
              {t("side.todo")}
            </button>
          </div>

          <nav className="sample-list" aria-label={t("side.tasks")}>
            {sections.map((section) => {
              const visible = section.tasks.filter(
                ({ task }) => filter === "all" || !done(task),
              );
              if (!visible.length && filter === "todo") return null;
              const open = openSections.has(section.modality);
              const completeInSection = section.tasks.filter(({ task }) =>
                done(task),
              ).length;
              const Icon = icons[section.modality];
              const sectionId =
                "S" + (MODALITY_ORDER.indexOf(section.modality) + 1);
              return (
                <section className="task-section" key={section.modality}>
                  <button
                    className="task-section-heading"
                    aria-expanded={open}
                    onClick={() =>
                      setOpenSections((previous) => {
                        const next = new Set(previous);
                        if (next.has(section.modality))
                          next.delete(section.modality);
                        else next.add(section.modality);
                        return next;
                      })
                    }
                  >
                    {open ? (
                      <ChevronDown size={15} />
                    ) : (
                      <ChevronRight size={15} />
                    )}
                    <Icon size={16} />
                    <strong>
                      {sectionId}{" "}
                      {t(("modality." + section.modality) as Key)}
                    </strong>
                    <span>
                      {completeInSection}/{section.tasks.length}
                    </span>
                  </button>
                  {open && (
                    <div className="task-section-items">
                      {visible.map(({ task, position }) => {
                        const complete = done(task);
                        return (
                          <button
                            key={task.task_id}
                            className={
                              "task-item " +
                              (selected === task.task_id ? "selected" : "")
                            }
                            onClick={() => onSelect(task)}
                            disabled={disabled}
                            aria-current={
                              selected === task.task_id ? "true" : undefined
                            }
                          >
                            <span>
                              {sectionId}-{position}
                            </span>
                            {complete ? (
                              <Check
                                size={16}
                                className="teal-text"
                                aria-label={t("side.done")}
                              />
                            ) : null}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </section>
              );
            })}
          </nav>

          {selectedTask && selectedLocation && (
            <div className="sidebar-ticket">
              <span>{t("side.ticket")}</span>
              <strong>
                {ticketId(
                  annotator,
                  selectedTask.modality,
                  selectedLocation.position,
                )}
              </strong>
            </div>
          )}
        </>
      )}
    </aside>
  );
}
