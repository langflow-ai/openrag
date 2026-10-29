import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { server } from "@/test-utils/msw/server";
import { renderWithProviders } from "@/test-utils/render";
import { moveDisabledPagesLast } from "./website-pages/page-sort";
import { WebsitePagesView } from "./website-pages-view";

const tableProps = vi.hoisted(() => ({ current: null as unknown }));

vi.mock("@/components/knowledge-data-table", () => ({
  KnowledgeDataTable: (props: { rows: { filename: string }[] }) => {
    tableProps.current = props;
    return (
      <div data-testid="website-page-table">
        {props.rows.map((page) => page.filename)}
      </div>
    );
  },
}));

vi.mock("@/components/knowledge-pagination-footer", () => ({
  KnowledgePaginationFooter: () => (
    <div data-testid="website-page-pagination" />
  ),
}));

describe("WebsitePagesView", () => {
  it("keeps disabled rows after active rows even after AG Grid sorts them", () => {
    const nodes = [
      { data: { filename: "Archived", status: "disabled" } },
      { data: { filename: "Guide", status: "active" } },
      { data: { filename: "Reference", status: "active" } },
    ];

    moveDisabledPagesLast(nodes as never);

    expect(nodes.map((node) => node.data.filename)).toEqual([
      "Guide",
      "Reference",
      "Archived",
    ]);
  });

  it("loads a website source, renders its searched pages, and syncs the source", async () => {
    const user = userEvent.setup();
    let syncCalls = 0;
    let taskRequests = 0;
    let searchPayload: { query?: string; resultMode?: string } | undefined;

    renderWithProviders(
      <WebsitePagesView sourceId="source-1" initialSearch="baseball" />,
      {
        providers: ["brand", "knowledgeFilter", "task"],
        auth: authPresets.admin,
        brand: "oss",
        handlers: [
          http.get("/api/connectors/url/sources/source-1", () =>
            HttpResponse.json({
              id: "source-1",
              name: "Docs",
              starting_url: "https://docs.example.com",
              status: "active",
              web_child_count: 1,
            }),
          ),
          http.post("/api/search", async ({ request }) => {
            searchPayload = (await request.json()) as {
              query?: string;
              resultMode?: string;
            };
            return HttpResponse.json({
              results: [
                {
                  document_id: "doc-1",
                  filename: "Getting started",
                  source_url: "https://docs.example.com/start",
                  mimetype: "text/html",
                  page: 1,
                  text: "Start here",
                  score: 1,
                  status: "active",
                },
              ],
              warnings: [],
            });
          }),
          http.post("/api/connectors/url/sources/source-1/sync", () => {
            syncCalls += 1;
            return HttpResponse.json({ task_id: "task-1" });
          }),
          http.get("/api/tasks/enhanced", () => {
            taskRequests += 1;
            return HttpResponse.json({ tasks: [] });
          }),
        ],
      },
    );

    expect(
      await screen.findByRole("heading", { name: "Docs" }),
    ).toBeInTheDocument();
    expect(await screen.findByTestId("website-page-table")).toHaveTextContent(
      "Getting started",
    );
    expect(searchPayload).toMatchObject({
      query: "baseball",
      resultMode: "website_pages",
    });
    expect(tableProps.current).not.toBeNull();
    await waitFor(() => expect(taskRequests).toBeGreaterThan(0));
    const taskRequestsBeforeSync = taskRequests;

    await user.click(screen.getByRole("button", { name: "Sync" }));
    await waitFor(() => expect(syncCalls).toBe(1));
    await waitFor(() =>
      expect(taskRequests).toBeGreaterThan(taskRequestsBeforeSync + 1),
    );
  });
});
