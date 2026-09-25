import {
  act,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { File } from "@/app/api/queries/useGetSearchQuery";
import { authPresets } from "@/test-utils/fixtures/auth";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, renderWithProviders } from "@/test-utils/render";
import { mockRouter } from "@/test-utils/router";
import { useWebsitePageColumns } from "./use-website-page-columns";
import { useWebsitePagesTable } from "./use-website-pages-table";
import { useWebsiteSource } from "./use-website-source";
import { WebsitePagesHeader } from "./website-pages-header";
import { WebsitePagesToolbar } from "./website-pages-toolbar";

function page(overrides: Partial<File> = {}): File {
  return {
    document_id: "doc-1",
    filename: "Getting started",
    source_url: "https://docs.example.com/getting-started",
    size: 1024,
    chunkCount: 2,
    status: "active",
    web_page_id: "page-1",
    web_page_depth: 1,
    embedding_model: "text-embedding-3-small",
    embedding_dimensions: 1536,
    ...overrides,
  } as File;
}

function ToolbarHarness({
  onSearch,
  onSync,
}: {
  onSearch(value: string): void;
  onSync(): void;
}) {
  const [search, setSearch] = useState("");
  return (
    <WebsitePagesToolbar
      search={search}
      onSearch={(value) => {
        setSearch(value);
        onSearch(value);
      }}
      isCloudBrand={false}
      isSyncing={false}
      onSync={onSync}
    />
  );
}

describe("website page data", () => {
  it("loads the source and searches, sorts, and paginates its website pages", async () => {
    const requests: string[] = [];
    server.use(
      http.get("/api/connectors/url/sources/source-1", () =>
        HttpResponse.json({
          id: "source-1",
          name: "Docs",
          starting_url: "https://docs.example.com",
          status: "active",
        }),
      ),
      http.post("/api/search", async ({ request }) => {
        const body = (await request.json()) as { query: string };
        requests.push(body.query);
        return HttpResponse.json({
          results: [
            page({
              filename: "Zebra",
              size: 1,
              web_page_depth: 9,
              embedding_model: "z-model",
              embedding_dimensions: 9999,
            }),
            page({
              document_id: "doc-2",
              filename: "Alpha",
              size: 2,
              web_page_depth: 1,
              embedding_model: "a-model",
              embedding_dimensions: 100,
            }),
          ],
          warnings: [],
        });
      }),
    );
    let sortState: { colId: string; sort: "asc" | "desc" } | undefined;
    const gridRef = {
      current: {
        api: { getColumnState: () => (sortState ? [sortState] : []) },
      },
    } as never;
    const source = renderHook(() => useWebsiteSource("source-1"));
    const table = renderHook(() => useWebsitePagesTable("source-1", gridRef), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() =>
      expect(source.result.current.source?.name).toBe("Docs"),
    );
    await waitFor(() => expect(table.result.current.total).toBe(2));
    expect(table.result.current.pages.map((item) => item.filename)).toEqual([
      "Alpha",
      "Zebra",
    ]);

    act(() => {
      table.result.current.setCurrentPageSize(1);
      table.result.current.setCurrentPage(2);
    });
    expect(table.result.current.pages.map((item) => item.filename)).toEqual([
      "Zebra",
    ]);

    for (const colId of ["size", "chunkCount", "status", "source_url"]) {
      sortState = { colId, sort: "desc" };
      act(() => table.result.current.onSortChanged());
    }

    for (const colId of [
      "web_page_depth",
      "embedding_model",
      "embedding_dimensions",
    ]) {
      sortState = { colId, sort: "desc" };
      act(() => table.result.current.onSortChanged());
      expect(table.result.current.pages.map((item) => item.filename)).toEqual([
        "Zebra",
      ]);
    }

    act(() => table.result.current.updateSearch("guide"));
    await waitFor(() => expect(requests).toContain("guide"));
    expect(table.result.current.currentPage).toBe(1);
  });
});

describe("website page presentation", () => {
  it("renders source metadata and sends users back to project knowledge", async () => {
    const user = userEvent.setup();
    const onNavigateBack = vi.fn();
    render(
      <WebsitePagesHeader
        source={{
          id: "source-1",
          name: "Docs",
          starting_url: "https://docs.example.com",
          status: "active",
          web_child_count: 3,
          last_successful_sync_at: "2026-09-25T13:39:19.000Z",
        }}
        pageCount={2}
        onNavigateBack={onNavigateBack}
      />,
    );

    expect(
      screen.getByRole("link", { name: "https://docs.example.com" }),
    ).toHaveAttribute("href", "https://docs.example.com");
    expect(screen.getByText("3 pages indexed")).toBeInTheDocument();
    expect(screen.getByText(/Last synced 25\/09\/2026/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Project knowledge" }));
    expect(onNavigateBack).toHaveBeenCalledOnce();
  });

  it("uses the shared search toolbar and exposes the source sync action", async () => {
    const user = userEvent.setup();
    const onSearch = vi.fn();
    const onSync = vi.fn();
    renderWithProviders(
      <ToolbarHarness onSearch={onSearch} onSync={onSync} />,
      {
        providers: ["brand", "knowledgeFilter"],
        auth: authPresets.admin,
        brand: "oss",
      },
    );

    await user.type(
      screen.getByPlaceholderText("Search your documents..."),
      "docs",
    );
    await user.keyboard("{Enter}");
    expect(onSearch).toHaveBeenLastCalledWith("docs");
    await user.click(screen.getByRole("button", { name: "Sync" }));
    expect(onSync).toHaveBeenCalledOnce();
  });

  it("routes page actions through the shared column factory", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      useWebsitePageColumns({
        sourceId: "source-1",
        isCloudBrand: false,
        onAction,
      }),
    );
    const data = page();
    const title = result.current.find((column) => column.field === "filename");
    const url = result.current.find((column) => column.field === "source_url");
    const model = result.current.find(
      (column) => column.field === "embedding_model",
    );
    const dimensions = result.current.find(
      (column) => column.field === "embedding_dimensions",
    );
    const status = result.current.find((column) => column.field === "status");
    const actions = result.current.find((column) => column.colId === "actions");

    render(
      title?.cellRenderer?.({ data, value: data.filename } as never) as never,
    );
    await user.click(screen.getByRole("button", { name: "Getting started" }));
    expect(mockRouter.push).toHaveBeenCalledWith(
      "/knowledge/chunks?document_id=doc-1&web_source_id=source-1",
    );

    render(url?.cellRenderer?.({ value: data.source_url } as never) as never);
    render(model?.cellRenderer?.({ data } as never) as never);
    render(dimensions?.cellRenderer?.({ data } as never) as never);
    render(status?.cellRenderer?.({ value: "active" } as never) as never);
    expect(screen.getByRole("link", { name: data.source_url })).toHaveAttribute(
      "href",
      data.source_url,
    );
    expect(screen.getByText("text-embedding-3-small")).toBeInTheDocument();
    expect(screen.getByText("1536")).toBeInTheDocument();

    render(actions?.cellRenderer?.({ data } as never) as never);
    await user.click(screen.getByRole("button", { name: "Page actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Re-sync page" }));
    expect(onAction).toHaveBeenCalledWith(
      "/api/connectors/url/sources/source-1/pages/page-1/sync",
    );

    await user.click(screen.getByRole("button", { name: "Page actions" }));
    await user.click(screen.getByRole("menuitem", { name: "View chunks" }));
    expect(mockRouter.push).toHaveBeenLastCalledWith(
      "/knowledge/chunks?document_id=doc-1&web_source_id=source-1",
    );

    await user.click(screen.getByRole("button", { name: "Page actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete page" }));
    expect(onAction).toHaveBeenLastCalledWith(
      "/api/connectors/url/sources/source-1/pages/page-1",
      "DELETE",
    );
  });
});
