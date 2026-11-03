import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { useState } from "react";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";
import {
  type SearchSuggestResult,
  SUGGEST_MAX_CHARS,
} from "@/app/api/queries/useGetSearchSuggestions";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { authPresets } from "@/test-utils/fixtures/auth";
import { server } from "@/test-utils/msw/server";
import { renderWithProviders } from "@/test-utils/render";
import { mockRouter } from "@/test-utils/router";
import { KnowledgeSearchBar } from "./knowledge-search-bar";

const PAYLOAD: SearchSuggestResult = {
  phase: "semantic",
  query: "docl",
  suggestions: [{ text: "docling", files: 2, chunks: 61 }],
  files: [
    {
      filename: "docling.pdf",
      mimetype: "application/pdf",
      connector_type: "local",
      preview: null,
    },
  ],
};

function serveSuggest() {
  const requests: unknown[] = [];
  server.use(
    http.post("/api/search/suggest", async ({ request }) => {
      requests.push(await request.json());
      return HttpResponse.json(PAYLOAD);
    }),
  );
  return requests;
}

/** KnowledgeDropdown, rendered inside the bar, loads these on mount. */
function serveDropdownDefaults() {
  server.use(
    http.get("/api/upload_options", () => HttpResponse.json({})),
    http.get("/api/connectors", () => HttpResponse.json({ connectors: {} })),
    http.get("/api/connectors/:type/defaults", () => HttpResponse.json({})),
  );
}

function Committed() {
  const { queryOverride } = useKnowledgeFilter();
  return <output data-testid="committed">{queryOverride}</output>;
}

async function renderBar() {
  serveDropdownDefaults();
  const user = userEvent.setup();
  renderWithProviders(
    <>
      <Committed />
      <KnowledgeSearchBar />
    </>,
    {
      providers: ["knowledgeFilter", "task", "brand"],
      brand: "ibm_cloud",
    },
  );
  const input = await screen.findByRole("combobox");
  return { user, input };
}

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

describe("KnowledgeSearchBar suggestions", () => {
  it("opens suggestions while typing", async () => {
    serveSuggest();
    const { user, input } = await renderBar();

    await user.click(input);
    await user.type(input, "docl");

    expect(input).toHaveAttribute("role", "combobox");
    expect(
      await screen.findByRole("option", { name: /docling\.pdf/ }),
    ).toBeInTheDocument();
  });

  it("picking a suggestion fills the input and commits the search", async () => {
    serveSuggest();
    const { user, input } = await renderBar();
    await user.click(input);
    await user.type(input, "docl");

    await user.click(await screen.findByRole("option", { name: /61 chunks/ }));

    expect(input).toHaveValue("docling");
    expect(screen.getByTestId("committed")).toHaveTextContent("docling");
  });

  it("picking a file opens its chunks with the typed query", async () => {
    serveSuggest();
    const { user, input } = await renderBar();
    await user.click(input);
    await user.type(input, "docl");

    await user.click(
      await screen.findByRole("option", { name: /docling\.pdf/ }),
    );

    expect(mockRouter.push).toHaveBeenCalledWith(
      "/knowledge/chunks?filename=docling.pdf&q=docl",
    );
  });

  it("submitting closes the dropdown and commits the trimmed text", async () => {
    serveSuggest();
    const { user, input } = await renderBar();
    await user.click(input);
    await user.type(input, "docl ");
    await screen.findByRole("listbox");

    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId("committed")).toHaveTextContent(/^docl$/);
  });

  it("clearing the input resets the committed search and stops suggesting", async () => {
    serveSuggest();
    const { user, input } = await renderBar();
    await user.click(input);
    await user.type(input, "docl");
    await screen.findByRole("listbox");

    await user.click(screen.getByRole("button", { name: "Clear search" }));

    expect(input).toHaveValue("");
    expect(screen.getByTestId("committed")).toHaveTextContent(/^$/);
    await waitFor(() =>
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument(),
    );
  });

  it("stops accepting characters at the cap and shows an error popup", async () => {
    serveSuggest();
    const errorToast = vi.spyOn(toast, "error").mockReturnValue("toast");
    const { user, input } = await renderBar();
    await user.click(input);

    await user.type(input, "a".repeat(SUGGEST_MAX_CHARS));
    expect(errorToast).not.toHaveBeenCalled();

    await user.type(input, "b");

    expect(input).toHaveValue("a".repeat(SUGGEST_MAX_CHARS));
    expect(errorToast).toHaveBeenCalledWith(
      `Search is limited to ${SUGGEST_MAX_CHARS} characters.`,
      expect.anything(),
    );
  });

  it("truncates pasted text to the cap", async () => {
    serveSuggest();
    vi.spyOn(toast, "error").mockReturnValue("toast");
    const { user, input } = await renderBar();
    await user.click(input);

    await user.paste("a".repeat(SUGGEST_MAX_CHARS + 25));

    expect(input).toHaveValue("a".repeat(SUGGEST_MAX_CHARS));
  });

  it("does not request suggestions until the input has focus", async () => {
    const requests = serveSuggest();
    const { input } = await renderBar();

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 500));
    });

    expect(input).toHaveValue("");
    expect(requests).toHaveLength(0);
  });
});
