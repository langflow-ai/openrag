import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "@/test-utils/render";
import { CancelIngestionButton } from "./cancel-ingestion-button";

describe("CancelIngestionButton", () => {
  it("renders with the cancel aria-label", () => {
    renderWithProviders(
      <CancelIngestionButton
        taskId="t1"
        filePath="file.pdf"
        onCancel={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(
      screen.getByRole("button", { name: /cancel file ingestion/i }),
    ).toBeInTheDocument();
  });

  it("calls onCancel with the correct taskId and filePath when clicked", async () => {
    const onCancel = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderWithProviders(
      <CancelIngestionButton
        taskId="task-abc"
        filePath="docs/report.pdf"
        onCancel={onCancel}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: /cancel file ingestion/i }),
    );

    expect(onCancel).toHaveBeenCalledOnce();
    expect(onCancel).toHaveBeenCalledWith("task-abc", "docs/report.pdf");
  });

  it("disables the button while the cancel is in-flight", async () => {
    // onCancel never resolves so the button stays in the loading state.
    const onCancel = vi.fn().mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();

    renderWithProviders(
      <CancelIngestionButton
        taskId="t1"
        filePath="file.pdf"
        onCancel={onCancel}
      />,
    );

    const button = screen.getByRole("button", {
      name: /cancel file ingestion/i,
    });
    await user.click(button);

    expect(button).toBeDisabled();
  });

  it("re-enables the button after onCancel resolves", async () => {
    const onCancel = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderWithProviders(
      <CancelIngestionButton
        taskId="t1"
        filePath="file.pdf"
        onCancel={onCancel}
      />,
    );

    const button = screen.getByRole("button", {
      name: /cancel file ingestion/i,
    });
    await user.click(button);

    expect(button).not.toBeDisabled();
  });
});
