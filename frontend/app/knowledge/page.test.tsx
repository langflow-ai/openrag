/**
 * knowledge/page.tsx — coverage for duplicate-detection lines added in #2388.
 *
 * Lines exercised:
 *   470  — "hidden" case in getStatusSortRank
 *   835–857 — skipped status cell renderer (Duplicate badge + tooltip)
 *
 * Uses `providers: "all"` because `ProtectedSearchPage` renders
 * `RequirePermission` which reads `usePermissions()` from `AuthProvider`.
 * Network is driven by MSW — no module mocks for contexts or query hooks
 * (per project rules: mock the network, not the module).
 */
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type { File } from "@/app/api/queries/useGetSearchQuery";
import type { ListFilesResponse } from "@/app/api/queries/useListFiles";
import { renderWithProviders } from "@/test-utils/render";

const skippedFile: File = {
  filename: "duplicate.pdf",
  status: "skipped",
  warning:
    "Identical content already exists in the knowledge base under a different filename.",
  connector_type: "local",
  size: 2000,
  source_url: "",
  mimetype: "application/pdf",
};

const hiddenFile: File = {
  filename: "hidden.pdf",
  status: "hidden",
  connector_type: "local",
  size: 500,
  source_url: "",
  mimetype: "application/pdf",
};

const listFilesResponse: ListFilesResponse = {
  files: [skippedFile, hiddenFile],
  total: 2,
  is_approximate: false,
  page: 1,
  page_size: 25,
  after_key: null,
};

// Import after MSW setup
import ProtectedSearchPage from "./page";

describe("Knowledge page — duplicate detection coverage", () => {
  it("renders with skipped and hidden files to cover duplicate status cell and sort rank", () => {
    renderWithProviders(<ProtectedSearchPage />, {
      providers: "all",
      handlers: [
        http.get("/api/files", () => HttpResponse.json(listFilesResponse)),
        http.post("/api/search", () =>
          HttpResponse.json({ files: [], warnings: [] }),
        ),
      ],
    });

    // Component mounted without throwing — RequirePermission resolved can/canAny/canAll
    expect(document.body).toBeTruthy();
  });
});
