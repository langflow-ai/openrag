import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { SearchSuggestResult } from "@/app/api/queries/useGetSearchSuggestions";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper } from "@/test-utils/render";
import {
  SearchSuggestionsPopover,
  useSearchSuggestionsBox,
} from "./search-suggestions";

const PAYLOAD: SearchSuggestResult = {
  phase: "semantic",
  query: "docl",
  suggestions: [
    { text: "docling", files: 2, chunks: 61 },
    { text: "docling serve", files: 1, chunks: 1 },
  ],
  files: [
    {
      filename: "docling.pdf",
      mimetype: "application/pdf",
      connector_type: "local",
      preview: { text: "Run <mark>docling</mark> serve", kind: "keyword" },
    },
    {
      filename: "notes.md",
      mimetype: "text/markdown",
      connector_type: "local",
      preview: { text: "Plain semantic sentence here.", kind: "semantic" },
    },
  ],
};

function serve(payload: SearchSuggestResult | { error: string }, status = 200) {
  const requests: unknown[] = [];
  server.use(
    http.post("/api/search/suggest", async ({ request }) => {
      requests.push(await request.json());
      return HttpResponse.json(payload, { status });
    }),
  );
  return requests;
}

interface HarnessProps {
  initialQuery?: string;
  enabled?: boolean;
  onPickSuggestion?: (text: string) => void;
  onPickFile?: (filename: string) => void;
}

function Harness({
  initialQuery = "",
  enabled = true,
  onPickSuggestion = () => {},
  onPickFile = () => {},
}: HarnessProps) {
  const [query, setQuery] = useState(initialQuery);
  const box = useSearchSuggestionsBox({
    query,
    filters: undefined,
    enabled,
    onPickSuggestion: (text) => {
      setQuery(text);
      onPickSuggestion(text);
    },
    onPickFile,
  });
  return (
    <SearchSuggestionsPopover box={box} query={query}>
      <div {...box.anchorProps}>
        <input
          aria-label="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          {...box.inputProps}
        />
        <button type="button" onClick={box.dismiss}>
          dismiss
        </button>
      </div>
    </SearchSuggestionsPopover>
  );
}

function setup(props: HarnessProps = {}) {
  const Wrapper = createQueryWrapper();
  const user = userEvent.setup();
  render(
    <Wrapper>
      <Harness {...props} />
    </Wrapper>,
  );
  return { user, input: screen.getByLabelText("search") };
}

async function openWithResults(user: ReturnType<typeof userEvent.setup>) {
  const input = screen.getByLabelText("search");
  await user.click(input);
  await user.type(input, "docl");
  await screen.findByRole("option", { name: /docling serve/ });
  return input;
}

describe("search suggestions dropdown", () => {
  it("stays closed until the input is focused and long enough", async () => {
    serve(PAYLOAD);
    const { user, input } = setup();

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    await user.click(input);
    await user.type(input, "d");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("renders suggestions and files in labelled sections", async () => {
    serve(PAYLOAD);
    const { user } = setup();
    await openWithResults(user);

    expect(screen.getByText("Suggestions")).toBeInTheDocument();
    expect(screen.getByText("Files")).toBeInTheDocument();
    expect(screen.getAllByRole("option")).toHaveLength(4);
    expect(screen.getByText("2 files · 61 chunks")).toBeInTheDocument();
    expect(screen.getByText("1 file · 1 chunk")).toBeInTheDocument();
    expect(screen.getByText("Plain semantic sentence here.")).toBeVisible();
  });

  it("marks the keyword match inside a file preview", async () => {
    serve(PAYLOAD);
    const { user } = setup();
    await openWithResults(user);

    const mark = document.querySelector("mark");
    expect(mark?.textContent).toBe("docling");
  });

  it("keeps non-option rows out of the listbox's option set", async () => {
    serve(PAYLOAD);
    const { user } = setup();
    await openWithResults(user);

    for (const label of ["Suggestions", "Files"]) {
      expect(screen.getByText(label)).toHaveAttribute("role", "presentation");
    }
  });

  it("shows a loading row while the first response is pending", async () => {
    server.use(
      http.post("/api/search/suggest", async () => {
        await new Promise((resolve) => setTimeout(resolve, 300));
        return HttpResponse.json(PAYLOAD);
      }),
    );
    const { user, input } = setup();
    await user.click(input);
    await user.type(input, "docl");

    expect(await screen.findByText("Searching…")).toBeInTheDocument();
    await screen.findByRole("option", { name: /docling serve/ });
    expect(screen.queryByText("Searching…")).not.toBeInTheDocument();
  });

  it("shows an error row instead of searching forever when the request fails", async () => {
    serve({ error: "Suggestions unavailable" }, 500);
    const { user, input } = setup();
    await user.click(input);
    await user.type(input, "docl");

    expect(
      await screen.findByText(
        "Suggestions unavailable. Press Enter to search.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Searching…")).not.toBeInTheDocument();
  });

  it("shows an empty state when there is nothing to suggest", async () => {
    serve({ ...PAYLOAD, suggestions: [], files: [] });
    const { user, input } = setup();
    await user.click(input);
    await user.type(input, "docl");

    expect(
      await screen.findByText("No suggestions. Press Enter to search."),
    ).toBeInTheDocument();
  });

  it("never requests anything while disabled", async () => {
    const requests = serve(PAYLOAD);
    const { user, input } = setup({ enabled: false });
    await user.click(input);
    await user.type(input, "docling");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 700));
    });

    expect(requests).toHaveLength(0);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});

describe("search suggestions keyboard and pointer", () => {
  it("exposes combobox semantics and tracks the active option", async () => {
    serve(PAYLOAD);
    const { user } = setup();
    const input = await openWithResults(user);

    expect(input).toHaveAttribute("role", "combobox");
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).not.toHaveAttribute("aria-activedescendant");

    await user.keyboard("{ArrowDown}");
    const [first] = screen.getAllByRole("option");
    expect(first).toHaveAttribute("aria-selected", "true");
    expect(input).toHaveAttribute("aria-activedescendant", first.id);
  });

  it("wraps from the last option back to none, and ArrowUp from none to the last", async () => {
    serve(PAYLOAD);
    const { user } = setup();
    const input = await openWithResults(user);
    const options = screen.getAllByRole("option");

    await user.keyboard("{ArrowUp}");
    expect(input).toHaveAttribute(
      "aria-activedescendant",
      options[options.length - 1].id,
    );

    await user.keyboard("{ArrowDown}");
    expect(input).not.toHaveAttribute("aria-activedescendant");
  });

  it("Enter picks the highlighted suggestion", async () => {
    serve(PAYLOAD);
    const onPickSuggestion = vi.fn();
    const { user } = setup({ onPickSuggestion });
    await openWithResults(user);

    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");

    expect(onPickSuggestion).toHaveBeenCalledWith("docling serve");
    await waitFor(() =>
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument(),
    );
  });

  it("Enter picks a highlighted file and passes its filename", async () => {
    serve(PAYLOAD);
    const onPickFile = vi.fn();
    const { user } = setup({ onPickFile });
    await openWithResults(user);

    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");

    expect(onPickFile).toHaveBeenCalledWith("docling.pdf");
  });

  it("Enter with no highlighted row is left alone so the form can submit", async () => {
    serve(PAYLOAD);
    const onPickSuggestion = vi.fn();
    const onPickFile = vi.fn();
    const { user } = setup({ onPickSuggestion, onPickFile });
    await openWithResults(user);

    await user.keyboard("{Enter}");

    expect(onPickSuggestion).not.toHaveBeenCalled();
    expect(onPickFile).not.toHaveBeenCalled();
  });

  it("Escape dismisses until the text changes", async () => {
    serve(PAYLOAD);
    const { user } = setup();
    const input = await openWithResults(user);

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument(),
    );
    expect(input).toHaveAttribute("aria-expanded", "false");

    await user.type(input, "i");
    expect(await screen.findByRole("listbox")).toBeInTheDocument();
  });

  it("the dismiss action closes the dropdown", async () => {
    serve(PAYLOAD);
    const { user } = setup();
    await openWithResults(user);

    await user.click(screen.getByRole("button", { name: "dismiss" }));

    await waitFor(() =>
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument(),
    );
  });

  it("clicking a row picks it without taking focus from the input", async () => {
    serve(PAYLOAD);
    const onPickFile = vi.fn();
    const { user } = setup({ onPickFile });
    const input = await openWithResults(user);

    await user.click(screen.getByRole("option", { name: /notes\.md/ }));

    expect(onPickFile).toHaveBeenCalledWith("notes.md");
    expect(input).toHaveFocus();
  });

  it("hovering a row makes it the active option", async () => {
    serve(PAYLOAD);
    const { user } = setup();
    await openWithResults(user);

    const option = screen.getAllByRole("option")[1];
    await user.hover(option);

    expect(option).toHaveAttribute("aria-selected", "true");
  });

  it("ignores navigation keys while an IME composition is in progress", async () => {
    serve(PAYLOAD);
    const { user } = setup();
    const input = await openWithResults(user);

    fireEvent.keyDown(input, { key: "ArrowDown", isComposing: true });
    expect(input).not.toHaveAttribute("aria-activedescendant");

    fireEvent.keyDown(input, { key: "ArrowDown", isComposing: false });
    expect(input).toHaveAttribute("aria-activedescendant");
  });

  it("resets the active row when new results arrive", async () => {
    serve(PAYLOAD);
    const { user } = setup();
    const input = await openWithResults(user);
    await user.keyboard("{ArrowDown}");
    expect(input).toHaveAttribute("aria-activedescendant");

    serve({ ...PAYLOAD, suggestions: [PAYLOAD.suggestions[0]], files: [] });
    await user.type(input, "i");

    await waitFor(() =>
      expect(input).not.toHaveAttribute("aria-activedescendant"),
    );
  });
});
