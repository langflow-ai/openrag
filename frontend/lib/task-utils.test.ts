import { describe, expect, it } from "vitest";
import type { TaskFileEntry } from "@/app/api/queries/useGetTasksQuery";
import {
  countTaskFileEntriesByCategory,
  getTaskFileDialogStatusLabel,
  isTerminalTaskStatus,
} from "./task-utils";

function entry(overrides: Partial<TaskFileEntry> = {}): TaskFileEntry {
  return { status: "failed", ...overrides };
}

describe("getTaskFileDialogStatusLabel — cancellation branch", () => {
  it("returns 'Cancelled' for a file cancelled by the user via error message", () => {
    expect(
      getTaskFileDialogStatusLabel(entry({ error: "Task cancelled by user" })),
    ).toBe("Cancelled");
  });

  it("returns 'Cancelled' for a file with failure_phase 'cancelled'", () => {
    expect(
      getTaskFileDialogStatusLabel(entry({ failure_phase: "cancelled" })),
    ).toBe("Cancelled");
  });

  it("returns 'Cancelled' for file-level cancel error message", () => {
    expect(
      getTaskFileDialogStatusLabel(entry({ error: "File cancelled by user" })),
    ).toBe("Cancelled");
  });

  it("returns 'Cancelled' for 'file processing task cancelled' error", () => {
    expect(
      getTaskFileDialogStatusLabel(
        entry({ error: "file processing task cancelled" }),
      ),
    ).toBe("Cancelled");
  });

  it("returns a phase-based label for a non-cancelled failed file", () => {
    const label = getTaskFileDialogStatusLabel(
      entry({ failure_phase: "parsing" }),
    );
    expect(label).toBe("Parsing issue");
  });
});

describe("countTaskFileEntriesByCategory — cancelled bucket", () => {
  it("categorises a file with 'task cancelled by user' error as cancelled", () => {
    const counts = countTaskFileEntriesByCategory([
      [
        "file.pdf",
        entry({ status: "failed", error: "Task cancelled by user" }),
      ],
    ]);
    expect(counts.cancelled).toBe(1);
    expect(counts.system_error).toBe(0);
  });

  it("categorises a file with failure_phase 'cancelled' as cancelled", () => {
    const counts = countTaskFileEntriesByCategory([
      ["file.pdf", entry({ failure_phase: "cancelled" })],
    ]);
    expect(counts.cancelled).toBe(1);
    expect(counts.system_error).toBe(0);
  });

  it("categorises a non-cancelled failed file as system_error", () => {
    const counts = countTaskFileEntriesByCategory([
      ["file.pdf", entry({ failure_phase: "parsing" })],
    ]);
    expect(counts.system_error).toBe(1);
    expect(counts.cancelled).toBe(0);
  });
});

describe("isTerminalTaskStatus — cancelled status", () => {
  it("treats 'cancelled' as a terminal status", () => {
    expect(isTerminalTaskStatus("cancelled")).toBe(true);
  });

  it("does not treat in-progress statuses as terminal", () => {
    expect(isTerminalTaskStatus("pending")).toBe(false);
    expect(isTerminalTaskStatus("running")).toBe(false);
    expect(isTerminalTaskStatus("processing")).toBe(false);
  });
});
