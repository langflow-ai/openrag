import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders } from "@/test-utils/render";
import { KnowledgeSearchBar } from "./knowledge-search-bar";

function ControlledSearch({
  onSearch,
  onClear,
  onDelete,
}: {
  onSearch(value: string): void;
  onClear(): void;
  onDelete(): void;
}) {
  const [value, setValue] = useState("initial");
  return (
    <KnowledgeSearchBar
      value={value}
      onSearch={(next) => {
        setValue(next);
        onSearch(next);
      }}
      onClear={onClear}
      selectedCount={1}
      onDeleteSelected={onDelete}
    />
  );
}

describe("KnowledgeSearchBar", () => {
  it("submits and clears a controlled search while retaining its standard actions", async () => {
    const user = userEvent.setup();
    const onSearch = vi.fn();
    const onClear = vi.fn();
    const onDelete = vi.fn();
    renderWithProviders(
      <ControlledSearch
        onSearch={onSearch}
        onClear={onClear}
        onDelete={onDelete}
      />,
      {
        providers: ["brand", "knowledgeFilter", "task"],
        auth: authPresets.admin,
        brand: "oss",
        handlers: [
          http.get("/api/upload_options", () => HttpResponse.json({})),
          http.get("/api/connectors/aws_s3/defaults", () =>
            HttpResponse.json({}),
          ),
          http.get("/api/connectors/ibm_cos/defaults", () =>
            HttpResponse.json({}),
          ),
          http.get("/api/connectors/azure_blob/defaults", () =>
            HttpResponse.json({}),
          ),
        ],
      },
    );

    const input = screen.getByPlaceholderText("Search your documents...");
    await user.clear(input);
    await user.type(input, "docs");
    await user.keyboard("{Enter}");
    expect(onSearch).toHaveBeenLastCalledWith("docs");

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("button", { name: "Clear search" }));
    expect(onClear).toHaveBeenCalledOnce();
    expect(onSearch).toHaveBeenLastCalledWith("");
  });
});
