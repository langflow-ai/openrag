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
import { useGetWebsiteSourceQuery } from "@/app/api/queries/useGetWebsiteSourceQuery";
import { authPresets } from "@/test-utils/fixtures/auth";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, renderWithProviders } from "@/test-utils/render";
import { mockRouter } from "@/test-utils/router";
import { useWebsitePageColumns } from "./use-website-page-columns";
import { useWebsitePagesTable } from "./use-website-pages-table";
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
    const source = renderHook(() => useGetWebsiteSourceQuery("source-1"), {
      wrapper: createQueryWrapper(),
    });
    const table = renderHook(() => useWebsitePagesTable("source-1", gridRef), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(source.result.current.data?.name).toBe("Docs"));
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

  it("refreshes a processing source until its successful sync is available", async () => {
    let sourceRequests = 0;
    let poll: (() => void) | undefined;
    const originalSetInterval = window.setInterval;
    const setIntervalSpy = vi
      .spyOn(window, "setInterval")
      .mockImplementation((handler, timeout, ...args) => {
        if (timeout === 2_000) {
          poll = typeof handler === "function" ? handler : undefined;
          return 1 as unknown as NodeJS.Timeout;
        }
        return originalSetInterval(
          handler,
          timeout,
          ...args,
        ) as unknown as NodeJS.Timeout;
      });
    server.use(
      http.get("/api/connectors/url/sources/source-1", () => {
        sourceRequests += 1;
        return HttpResponse.json({
          id: "source-1",
          name: "Docs",
          starting_url: "https://docs.example.com",
          status: sourceRequests === 1 ? "processing" : "active",
          last_successful_sync_at:
            sourceRequests === 1 ? null : "2026-09-25T13:39:19.000Z",
        });
      }),
    );

    const source = renderHook(() => useGetWebsiteSourceQuery("source-1"), {
      wrapper: createQueryWrapper(),
    });

    try {
      await waitFor(() =>
        expect(source.result.current.data?.status).toBe("processing"),
      );
      await waitFor(() => expect(poll).toBeDefined());

      act(() => poll?.());

      await waitFor(() =>
        expect(source.result.current.data?.last_successful_sync_at).toBe(
          "2026-09-25T13:39:19.000Z",
        ),
      );
    } finally {
      source.unmount();
      setIntervalSpy.mockRestore();
    }
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
    const lastSynced = new Intl.DateTimeFormat("en-GB", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date("2026-09-25T13:39:19.000Z"));
    expect(screen.getByText(`Last synced ${lastSynced}`)).toBeInTheDocument();
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
    expect(onAction).toHaveBeenCalledWith("page-1", "sync");

    await user.click(screen.getByRole("button", { name: "Page actions" }));
    await user.click(screen.getByRole("menuitem", { name: "View chunks" }));
    expect(mockRouter.push).toHaveBeenLastCalledWith(
      "/knowledge/chunks?document_id=doc-1&web_source_id=source-1",
    );

    await user.click(screen.getByRole("button", { name: "Page actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete page" }));
    expect(onAction).toHaveBeenLastCalledWith("page-1", "delete");
  });
});
