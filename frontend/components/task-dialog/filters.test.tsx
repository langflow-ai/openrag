import { describe, expect, it, vi } from "vitest";
import { ALL_TASK_FILE_TYPES } from "@/lib/task-utils";
import { render, screen, userEvent, within } from "@/test-utils/render";
import { TaskDialogFilters } from "./filters";

// TaskDialogFilters is props-only, so plain `render` is enough — no
// QueryClient needed. It reads `useIsCloudBrand`, but BrandContext has a
// default value, so these tests exercise the default (OSS) brand path.

function setup(
  overrides: Partial<Parameters<typeof TaskDialogFilters>[0]> = {},
) {
  const onSearchChange = vi.fn();
  const onFileTypeChange = vi.fn();

  render(
    <TaskDialogFilters
      search=""
      onSearchChange={onSearchChange}
      fileType={ALL_TASK_FILE_TYPES}
      onFileTypeChange={onFileTypeChange}
      fileTypes={["pdf", "docx"]}
      fileTypeLabel="All file types"
      searchDisabled={false}
      fileTypeDisabled={false}
      {...overrides}
    />,
  );

  return { onSearchChange, onFileTypeChange, user: userEvent.setup() };
}

describe("TaskDialogFilters", () => {
  it("reports each keystroke in the search field", async () => {
    const { onSearchChange, user } = setup();

    await user.type(screen.getByPlaceholderText("Search files..."), "ab");

    // Controlled input pinned to search="", so each call sees a single char.
    expect(onSearchChange).toHaveBeenCalledTimes(2);
    expect(onSearchChange).toHaveBeenNthCalledWith(1, "a");
    expect(onSearchChange).toHaveBeenNthCalledWith(2, "b");
  });

  it("disables the search field when searchDisabled is set", () => {
    setup({ searchDisabled: true });

    expect(screen.getByPlaceholderText("Search files...")).toBeDisabled();
  });

  it("opens the file type menu and lists all types plus the catch-all", async () => {
    const { user } = setup();

    await user.click(screen.getByRole("button", { name: /all file types/i }));

    const menu = await screen.findByRole("menu");
    const items = within(menu).getAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "All file types",
      "PDF",
      "DOCX",
    ]);
  });

  it("emits the raw file type value when an option is chosen", async () => {
    const { onFileTypeChange, user } = setup();

    await user.click(screen.getByRole("button", { name: /all file types/i }));
    await user.click(await screen.findByRole("menuitem", { name: "PDF" }));

    expect(onFileTypeChange).toHaveBeenCalledExactlyOnceWith("pdf");
  });

  it("marks the file type trigger disabled when fileTypeDisabled is set", () => {
    setup({ fileTypeDisabled: true });

    expect(
      screen.getByRole("button", { name: /all file types/i }),
    ).toBeDisabled();
  });

  // NOT TESTED HERE, ON PURPOSE: that a disabled trigger leaves the menu shut.
  // components/ui/button.tsx:7 enforces that with `disabled:pointer-events-none`,
  // a CSS rule. jsdom has no CSS engine, so Radix's pointerdown listener fires
  // anyway and the menu opens — the assertion would fail against code that is
  // correct in a real browser. CSS-enforced behaviour belongs in Playwright.
  // See R3 in local/plans/frontend-testing-foundation.md.
});
