import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders } from "@/test-utils/render";
import { KnowledgeSearchToolbar } from "./knowledge-search-toolbar";

function ControlledToolbar({ onSubmit }: { onSubmit(value: string): void }) {
  const [value, setValue] = useState("existing");
  return (
    <KnowledgeSearchToolbar
      value={value}
      onValueChange={setValue}
      onSubmit={() => onSubmit(value)}
      onClear={() => setValue("")}
      filter={<span>Active filter</span>}
      rightActions={<button type="button">Refresh</button>}
      nonCloudSearch={<span>Fallback search</span>}
    />
  );
}

describe("KnowledgeSearchToolbar", () => {
  it("uses the shared cloud search surface to edit, submit, and clear a search", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    renderWithProviders(<ControlledToolbar onSubmit={onSubmit} />, {
      providers: ["brand"],
      auth: authPresets.ibmAuthMode,
    });

    const input = await screen.findByRole("textbox");
    expect(screen.getByText("Active filter")).toBeVisible();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeVisible();

    await user.clear(input);
    await user.type(input, "website docs");
    await user.keyboard("{Enter}");
    expect(onSubmit).toHaveBeenCalledWith("website docs");

    await user.click(screen.getByRole("button", { name: "Clear search" }));
    expect(input).toHaveValue("");
  });
});
