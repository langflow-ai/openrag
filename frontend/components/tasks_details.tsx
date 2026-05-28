import { useEffect, useMemo, useState } from "react";
import { TaskCollapsibleSection } from "@/components/task-collapsible-section";
import { TaskErrorContent } from "@/components/task-error-content";
import { TaskPanelHeader } from "@/components/task-panel-header";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { type Task } from "@/contexts/task-context";
import { parseTimestampMs } from "@/lib/time-utils";

interface FailedTasksInfoProps {
  failedTasks: Task[];
}

export const FailedTasksInfo = ({ failedTasks }: FailedTasksInfoProps) => {
  const [openSections, setOpenSections] = useState<
    Record<"recent" | "past", boolean>
  >({
    recent: true,
    past: false,
  });
  const [nowMs, setNowMs] = useState(() => Date.now());
  const { closePanelOnly } = useKnowledgeFilter();

  useEffect(() => {
    const id = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(id);
    };
  }, []);

  const { recentTasks, pastTasks } = useMemo(() => {
    const fiveMinutesMs = 5 * 60 * 1000;

    const recent: Task[] = [];
    const past: Task[] = [];

    failedTasks.forEach((task) => {
      // Use created_at as stable anchor so tasks naturally move from
      // recent -> past even if updated_at gets refreshed by polling.
      const referenceMs =
        parseTimestampMs(task.created_at) ?? parseTimestampMs(task.updated_at);
      if (referenceMs === null) {
        past.push(task);
        return;
      }

      if (nowMs - referenceMs < fiveMinutesMs) {
        recent.push(task);
      } else {
        past.push(task);
      }
    });

    return { recentTasks: recent, pastTasks: past };
  }, [failedTasks, nowMs]);

  const sections = useMemo(
    () => [
      {
        sectionKey: "recent" as const,
        title: "Recent Tasks",
        tasks: recentTasks,
        emptyText: "No recent failed tasks.",
        mode: "recent" as const,
      },
      {
        sectionKey: "past" as const,
        title: "Past Tasks",
        tasks: pastTasks,
        emptyText: "No past failed tasks.",
        mode: "past" as const,
      },
    ],
    [recentTasks, pastTasks],
  );

  return (
    <div className="h-full bg-background border-l overflow-y-auto">
      <TaskPanelHeader onClose={closePanelOnly} />

      {failedTasks.length === 0 ? (
        <div className="p-4 text-sm text-muted-foreground space-x-3">
          No failed tasks.
        </div>
      ) : (
        <div>
          {sections.map((section) => (
            <TaskCollapsibleSection
              key={section.sectionKey}
              title={section.title}
              items={section.tasks}
              isOpen={openSections[section.sectionKey]}
              onToggle={() =>
                setOpenSections((prev) => ({
                  ...prev,
                  [section.sectionKey]: !prev[section.sectionKey],
                }))
              }
              emptyText={section.emptyText}
              renderItem={(task) => (
                <TaskErrorContent
                  key={`${section.sectionKey}-${task.task_id}`}
                  task={task}
                  mode={section.mode}
                  nowMs={nowMs}
                />
              )}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default FailedTasksInfo;
