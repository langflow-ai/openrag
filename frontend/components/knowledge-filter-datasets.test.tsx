/**
 * Knowledge filters: the `datasets` dimension, end to end through the panel.
 *
 * Semantics under test: a missing key = every dataset (all checked), unticking
 * writes the explicit remaining ids, none ticked writes `[]`, and whatever was
 * saved reaches the chat request unchanged.
 */
import { act, fireEvent } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { makeStatus } from "@/app/settings/_components/opensearch-snapshot/snapshot-fixtures";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useChatStreaming } from "@/hooks/useChatStreaming";
import type { SnapshotStatus } from "@/lib/opensearch-snapshot";
import { authPresets, withAuth } from "@/test-utils/fixtures/auth";
import { server } from "@/test-utils/msw/server";
import { renderWithProviders, screen, waitFor } from "@/test-utils/render";
import { KnowledgeFilterPanel } from "./knowledge-filter-panel";

vi.mock("@/lib/analytics", () => ({ trackButton: vi.fn() }));

// useChatStreaming only needs `refreshConversations` from the chat context;
// the provider is a passthrough because test-utils/render imports it.
vi.mock("@/contexts/chat-context", () => ({
  useChat: () => ({ refreshConversations: vi.fn() }),
  ChatProvider: ({ children }: { children: ReactNode }) => children,
}));

const SNAPSHOT = "/api/connectors/opensearch_snapshot";

const auth = withAuth(authPresets.admin, {
  me: { run_mode: "oss" },
  usersMe: { permissions: ["kf:create", "kf:edit:own"] },
});

const DATASETS = [
  { id: "ds-1", display_name: "Scientists", import_name: "Lab import" },
  { id: "ds-2", display_name: "Discoveries", import_name: "Lab import" },
  { id: "ds-3", display_name: "Journals", import_name: "Library import" },
].map((d) => ({
  ...d,
  import_id: "imp-1",
  description: "",
  source_index: "idx",
  shared: false,
  is_owner: true,
}));

interface Stored {
  id: string;
  name: string;
  description: string;
  owner: string;
  created_at: string;
  updated_at: string;
  query_data: string;
}

function filterWith(filters: Record<string, unknown>): Stored {
  return {
    id: "f1",
    name: "Lab filter",
    description: "",
    owner: "user-1",
    created_at: "",
    updated_at: "",
    query_data: JSON.stringify({
      query: "",
      filters: {
        data_sources: ["*"],
        document_types: ["*"],
        owners: ["*"],
        connector_types: ["*"],
        ...filters,
      },
      limit: 10,
      scoreThreshold: 0,
      color: "zinc",
      icon: "filter",
    }),
  };
}

interface Seen {
  stored: Stored;
  saved?: { filters: Record<string, unknown> };
  chat?: { filters?: Record<string, unknown>; filter_id?: string };
}

function Harness({ initial }: { initial: Stored }) {
  const { selectedFilter, setSelectedFilter } = useKnowledgeFilter();
  const { sendMessage } = useChatStreaming({ endpoint: "/api/chat" });
  return (
    <>
      <button type="button" onClick={() => setSelectedFilter(initial)}>
        select-saved
      </button>
      <button
        type="button"
        onClick={() => {
          // What the chat page does with the conversation's filter.
          const parsed = JSON.parse(selectedFilter?.query_data ?? "{}");
          void sendMessage({
            prompt: "hello",
            filters: parsed.filters,
            filter_id: selectedFilter?.id,
            limit: parsed.limit,
            scoreThreshold: parsed.scoreThreshold,
          });
        }}
      >
        send-chat
      </button>
      <KnowledgeFilterPanel />
    </>
  );
}

async function click(el: HTMLElement) {
  await act(async () => {
    fireEvent.click(el);
  });
}

async function renderPanel(
  filters: Record<string, unknown>,
  options: { status?: SnapshotStatus } = {},
) {
  const seen: Seen = { stored: filterWith(filters) };
  server.use(
    http.post("/api/search", () => HttpResponse.json({ aggregations: {} })),
    http.get(`${SNAPSHOT}/status`, () =>
      HttpResponse.json(options.status ?? makeStatus()),
    ),
    http.get(`${SNAPSHOT}/datasets`, () =>
      HttpResponse.json({ datasets: DATASETS }),
    ),
    http.put("/api/knowledge-filter/f1", async ({ request }) => {
      const body = (await request.json()) as { queryData: string };
      seen.stored = { ...seen.stored, query_data: body.queryData };
      seen.saved = JSON.parse(body.queryData);
      return HttpResponse.json({ success: true, filter: seen.stored });
    }),
    http.post("/api/chat", async ({ request }) => {
      seen.chat = (await request.json()) as Seen["chat"];
      return new HttpResponse(
        `${JSON.stringify({ object: "response.chunk", delta: { content: "ok" } })}\n`,
        { headers: { "Content-Type": "application/x-ndjson" } },
      );
    }),
  );
  renderWithProviders(<Harness initial={seen.stored} />, {
    providers: ["auth", "brand", "knowledgeFilter"],
    auth,
  });
  await click(screen.getByRole("button", { name: "select-saved" }));
  return seen;
}

const box = (name: string) => screen.findByRole("checkbox", { name });

async function save(seen: Seen) {
  await click(await screen.findByRole("button", { name: /update filter/i }));
  await waitFor(() => expect(seen.saved).toBeDefined());
  return seen.saved as { filters: Record<string, unknown> };
}

describe("Knowledge filter datasets checklist", () => {
  it("checks every dataset when the filter has no datasets key", async () => {
    const seen = await renderPanel({});
    expect(await box("All datasets")).toBeChecked();
    for (const name of ["Scientists", "Discoveries", "Journals"]) {
      expect(await box(name)).toBeChecked();
    }
    // Untouched: nothing is written, so the filter keeps meaning "all".
    expect(await save(seen)).toSatisfy(
      (data: { filters: object }) => !("datasets" in data.filters),
    );
  });

  it("writes explicit ids when a dataset is unticked", async () => {
    const seen = await renderPanel({});
    await click(await box("Discoveries"));
    expect(await box("All datasets")).toBePartiallyChecked();
    expect((await save(seen)).filters.datasets).toEqual(["ds-1", "ds-3"]);
  });

  it("returns to all (key omitted) when the last dataset is ticked again", async () => {
    const seen = await renderPanel({});
    await click(await box("Journals"));
    await click(await box("Journals"));
    const data = await save(seen);
    expect(data.filters).not.toHaveProperty("datasets");
  });

  it("writes [] when no dataset is ticked", async () => {
    const seen = await renderPanel({});
    await click(await box("All datasets"));
    for (const name of ["Scientists", "Discoveries", "Journals"]) {
      expect(await box(name)).not.toBeChecked();
    }
    expect((await save(seen)).filters.datasets).toEqual([]);
  });

  it("loads a saved [] as none ticked and lets one be ticked", async () => {
    const seen = await renderPanel({ datasets: [] });
    expect(await box("All datasets")).not.toBeChecked();
    expect(await box("Scientists")).not.toBeChecked();
    await click(await box("Scientists"));
    expect((await save(seen)).filters.datasets).toEqual(["ds-1"]);
  });

  it("keeps a saved explicit list exactly as saved", async () => {
    const seen = await renderPanel({ datasets: ["ds-2", "ds-gone"] });
    expect(await box("Discoveries")).toBeChecked();
    expect(await box("Scientists")).not.toBeChecked();
    expect((await save(seen)).filters.datasets).toEqual(["ds-2", "ds-gone"]);
  });

  it('treats a saved ["*"] as all datasets and saves it back unchanged', async () => {
    const seen = await renderPanel({ datasets: ["*"] });
    expect(await box("Scientists")).toBeChecked();
    expect((await save(seen)).filters.datasets).toEqual(["*"]);
  });

  it("hides the checklist when the connector is disabled", async () => {
    await renderPanel({}, { status: makeStatus({ enabled: false }) });
    await screen.findByRole("button", { name: /update filter/i });
    expect(
      screen.queryByRole("checkbox", { name: "All datasets" }),
    ).not.toBeInTheDocument();
  });

  it.each([
    ["an explicit list", { datasets: ["ds-1", "ds-3"] }, ["ds-1", "ds-3"]],
    ["none", { datasets: [] }, []],
  ])("carries %s from save → reload → chat request", async (_label, filters, expected) => {
    const seen = await renderPanel({});
    // Edit through the UI, save, and let the panel reload what the server stored.
    if (expected.length === 0) {
      await click(await box("All datasets"));
    } else {
      await click(await box("Discoveries"));
    }
    const data = await save(seen);
    expect(data.filters.datasets).toEqual(expected);
    expect(JSON.parse(seen.stored.query_data).filters).toMatchObject(filters);

    // The reloaded filter shows the same selection.
    const discoveries = await box("Discoveries");
    if (expected.includes("ds-2")) expect(discoveries).toBeChecked();
    else expect(discoveries).not.toBeChecked();

    await click(screen.getByRole("button", { name: "send-chat" }));
    await waitFor(() => expect(seen.chat).toBeDefined());
    expect(seen.chat?.filters?.datasets).toEqual(expected);
    expect(seen.chat?.filter_id).toBe("f1");
  });

  it("sends no datasets in the chat request when the filter selects all", async () => {
    const seen = await renderPanel({ datasets: ["*"] });
    await save(seen);
    await click(screen.getByRole("button", { name: "send-chat" }));
    await waitFor(() => expect(seen.chat).toBeDefined());
    expect(seen.chat?.filters ?? {}).not.toHaveProperty("datasets");
  });
});
