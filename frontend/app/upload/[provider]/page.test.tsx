import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import {
  renderWithProviders,
  screen,
  userEvent,
  waitFor,
} from "@/test-utils/render";
import { setMockLocation } from "@/test-utils/router";
import UploadProviderPage from "./page";

describe("plugin upload", () => {
  it("selects explicit files from nested pages and syncs opaque IDs with the exact connection ID, without an OAuth token", async () => {
    setMockLocation({
      pathname: "/upload/sharepoint_onprem",
      params: { provider: "sharepoint_onprem" },
    });
    const syncBodies: unknown[] = [];
    const tokenRequests: string[] = [];
    renderWithProviders(<UploadProviderPage />, {
      providers: ["auth", "brand", "task", "tooltip"],
      handlers: [
        http.get("/api/connectors", () =>
          HttpResponse.json({
            connectors: {
              sharepoint_onprem: {
                name: "SharePoint Server",
                description: "On-premises",
                icon: "",
                kind: "bucket",
                available: true,
                browse_capability: "hierarchical",
                config_fields: [
                  {
                    name: "root_url",
                    label: "Root URL",
                    type: "text",
                    required: true,
                  },
                ],
              },
            },
          }),
        ),
        http.get("/api/connectors/sharepoint_onprem/status", () =>
          HttpResponse.json({
            connections: [
              {
                connection_id: "my-exact-connection",
                is_active: true,
                is_authenticated: true,
              },
            ],
          }),
        ),
        http.get("/api/connectors/sharepoint_onprem/token", ({ request }) => {
          tokenRequests.push(request.url);
          return HttpResponse.json({ access_token: "wrong" });
        }),
        http.get(
          "/api/connectors/sharepoint_onprem/my-exact-connection/picker/children",
          ({ request }) => {
            const url = new URL(request.url);
            if (url.searchParams.get("parent_id") === "directory-id")
              return HttpResponse.json({
                nodes: [
                  {
                    id: "nested-file-id",
                    parent_id: "directory-id",
                    name: "nested.pdf",
                    kind: "file",
                  },
                ],
                next_cursor: null,
              });
            if (url.searchParams.get("cursor") === "page-two")
              return HttpResponse.json({
                nodes: [
                  {
                    id: "other-id",
                    parent_id: null,
                    name: "other.pdf",
                    kind: "file",
                  },
                ],
                next_cursor: null,
              });
            return HttpResponse.json({
              nodes: [
                {
                  id: "directory-id",
                  parent_id: null,
                  name: "Archive",
                  kind: "folder",
                },
                {
                  id: "first-id",
                  parent_id: null,
                  name: "first.pdf",
                  kind: "file",
                },
              ],
              next_cursor: "page-two",
            });
          },
        ),
        http.post("/api/connectors/sharepoint_onprem/check-duplicates", () =>
          HttpResponse.json({ duplicate_count: 0, duplicate_names: [] }),
        ),
        http.post(
          "/api/connectors/sharepoint_onprem/sync",
          async ({ request }) => {
            syncBodies.push(await request.json());
            return HttpResponse.json({ task_ids: ["task-one"] });
          },
        ),
      ],
    });
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("checkbox", { name: "Select first.pdf" }),
    );
    await user.click(screen.getByRole("button", { name: "Load More" }));
    await user.click(
      await screen.findByRole("checkbox", { name: "Select other.pdf" }),
    );
    await user.click(screen.getByRole("button", { name: "Archive" }));
    await user.click(
      await screen.findByRole("checkbox", { name: "Select nested.pdf" }),
    );
    await user.click(screen.getByRole("button", { name: "Ingest 3 items" }));
    await waitFor(() => expect(syncBodies).toHaveLength(1));
    expect(syncBodies[0]).toEqual(
      expect.objectContaining({
        connection_id: "my-exact-connection",
        selected_files: [
          expect.objectContaining({ id: "first-id" }),
          expect.objectContaining({ id: "other-id" }),
          expect.objectContaining({ id: "nested-file-id" }),
        ],
      }),
    );
    expect(tokenRequests).toHaveLength(0);
  });
});

describe("flat customer connector upload", () => {
  it("offers a root file picker rather than requiring an OAuth token", async () => {
    setMockLocation({
      pathname: "/upload/acme_flat",
      params: { provider: "acme_flat" },
    });
    let tokenCalled = false;
    renderWithProviders(<UploadProviderPage />, {
      providers: ["auth", "brand", "task", "tooltip"],
      handlers: [
        http.get("/api/connectors", () =>
          HttpResponse.json({
            connectors: {
              acme_flat: {
                name: "Acme Files",
                description: "File source",
                icon: "",
                kind: "bucket",
                available: true,
                browse_capability: "flat",
                config_fields: [],
              },
            },
          }),
        ),
        http.get("/api/connectors/acme_flat/status", () =>
          HttpResponse.json({
            connections: [
              {
                connection_id: "flat-owned",
                is_active: true,
                is_authenticated: true,
              },
            ],
          }),
        ),
        http.get("/api/connectors/acme_flat/token", () => {
          tokenCalled = true;
          return HttpResponse.json({ access_token: "unexpected" });
        }),
        http.get("/api/connectors/acme_flat/flat-owned/picker/children", () =>
          HttpResponse.json({
            nodes: [
              {
                id: "stable-file",
                parent_id: null,
                name: "guide.pdf",
                kind: "file",
              },
            ],
            next_cursor: null,
          }),
        ),
      ],
    });

    expect(
      await screen.findByRole("checkbox", { name: "Select guide.pdf" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Access Token Required")).not.toBeInTheDocument();
    expect(tokenCalled).toBe(false);
  });
});
