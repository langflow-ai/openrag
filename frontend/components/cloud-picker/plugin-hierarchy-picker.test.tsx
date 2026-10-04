import { HttpResponse, http } from "msw";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import {
  renderWithProviders,
  screen,
  userEvent,
  waitFor,
} from "@/test-utils/render";
import { PluginHierarchyPicker } from "./plugin-hierarchy-picker";
import type { CloudFile } from "./types";

function Picker() {
  const [files, setFiles] = useState<CloudFile[]>([]);
  return (
    <PluginHierarchyPicker
      provider="sharepoint_onprem"
      connectionId="connection-123"
      selectedFiles={files}
      onFileSelected={setFiles}
      isIngesting={false}
    />
  );
}

describe("PluginHierarchyPicker", () => {
  it("navigates folders and keeps exact file selections across paginated listings", async () => {
    const urls: URL[] = [];
    renderWithProviders(<Picker />, {
      providers: ["auth"],
      handlers: [
        http.get(
          "/api/connectors/sharepoint_onprem/connection-123/picker/children",
          ({ request }) => {
            const url = new URL(request.url);
            urls.push(url);
            if (url.searchParams.get("parent_id") === "dir/a") {
              if (url.searchParams.get("cursor") === "next-a")
                return HttpResponse.json({
                  nodes: [
                    {
                      id: "dir/a/first.txt",
                      parent_id: "dir/a",
                      name: "first.txt",
                      kind: "file",
                    },
                    {
                      id: "dir/a/second.txt",
                      parent_id: "dir/a",
                      name: "second.txt",
                      kind: "file",
                    },
                  ],
                  next_cursor: null,
                });
              return HttpResponse.json({
                nodes: [
                  {
                    id: "dir/a/first.txt",
                    parent_id: "dir/a",
                    name: "first.txt",
                    kind: "file",
                    size: 42,
                    is_ingested: true,
                    is_stale: true,
                  },
                ],
                next_cursor: "next-a",
              });
            }
            return HttpResponse.json({
              nodes: [
                {
                  id: "dir/a",
                  parent_id: null,
                  name: "Projects",
                  kind: "folder",
                },
                {
                  id: "root.txt",
                  parent_id: null,
                  name: "root.txt",
                  kind: "file",
                  is_ingested: true,
                },
              ],
              next_cursor: null,
            });
          },
        ),
      ],
    });
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("checkbox", { name: "Select root.txt" }),
    );
    expect(screen.getByText("Ingested")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Projects" }));
    await user.click(
      await screen.findByRole("checkbox", { name: "Select first.txt" }),
    );
    expect(screen.getByText("Update available")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load More" }));
    await user.click(
      await screen.findByRole("checkbox", { name: "Select second.txt" }),
    );
    expect(
      screen.getAllByRole("checkbox", { name: "Select first.txt" }),
    ).toHaveLength(1);
    expect(screen.getByText("Selected items (3)")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Root" }));
    expect(
      await screen.findByRole("checkbox", { name: "Select root.txt" }),
    ).toBeChecked();
    expect(screen.getByText("Selected items (3)")).toBeInTheDocument();
    expect(
      urls.some(
        (url) =>
          url.searchParams.get("parent_id") === "dir/a" &&
          url.searchParams.get("cursor") === "next-a" &&
          url.searchParams.get("page_size") === "100",
      ),
    ).toBe(true);
    expect(
      screen.queryByRole("checkbox", { name: "Select Projects" }),
    ).toBeNull();
    expect(screen.queryByRole("searchbox")).toBeNull();
  });

  it("shows remote permission errors and retries", async () => {
    let fail = true;
    renderWithProviders(<Picker />, {
      providers: ["auth"],
      handlers: [
        http.get(
          "/api/connectors/sharepoint_onprem/connection-123/picker/children",
          () => {
            if (fail) {
              fail = false;
              return HttpResponse.json(
                { error: "Access denied" },
                { status: 403 },
              );
            }
            return HttpResponse.json({
              nodes: [
                {
                  id: "allowed.txt",
                  parent_id: null,
                  name: "allowed.txt",
                  kind: "file",
                },
              ],
              next_cursor: null,
            });
          },
        ),
      ],
    });
    const user = userEvent.setup();
    expect(await screen.findByRole("alert")).toHaveTextContent("Access denied");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await user.click(
      await screen.findByRole("checkbox", { name: "Select allowed.txt" }),
    );
    await waitFor(() =>
      expect(screen.getByText("Selected items (1)")).toBeInTheDocument(),
    );
  });
});
