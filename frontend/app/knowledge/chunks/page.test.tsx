import { beforeEach, describe, expect, it, vi } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders, waitFor } from "@/test-utils/render";
import { setMockLocation } from "@/test-utils/router";

// Mock the hooks used by the page
const mockUseFileScopedChunksQuery = vi.fn();
vi.mock("@/app/api/queries/useFileScopedChunksQuery", () => ({
  useFileScopedChunksQuery: (filename: string | null, searchQuery?: string) =>
    mockUseFileScopedChunksQuery(filename, searchQuery),
}));

describe("ChunksPage - Search Query Parameter Handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("extracts searchQuery from URL and passes to useFileScopedChunksQuery (lines 21-22)", async () => {
    setMockLocation({
      pathname: "/knowledge/chunks",
      searchParams: { filename: "test.pdf", q: "search term" },
    });

    mockUseFileScopedChunksQuery.mockReturnValue({
      file: { filename: "test.pdf", chunks: [] },
      isFetching: false,
    });

    // Dynamically import after mocks are set up
    const { default: ProtectedChunksPage } = await import("./page");

    renderWithProviders(<ProtectedChunksPage />, {
      providers: ["auth"],
      auth: authPresets.admin,
    });

    // Wait for component to render and call the hook
    await waitFor(() => {
      expect(mockUseFileScopedChunksQuery).toHaveBeenCalledWith(
        "test.pdf",
        "search term",
      );
    });
  });

  it("passes undefined searchQuery when q param is not present (line 21)", async () => {
    setMockLocation({
      pathname: "/knowledge/chunks",
      searchParams: { filename: "test.pdf" },
    });

    mockUseFileScopedChunksQuery.mockReturnValue({
      file: { filename: "test.pdf", chunks: [] },
      isFetching: false,
    });

    const { default: ProtectedChunksPage } = await import("./page");

    renderWithProviders(<ProtectedChunksPage />, {
      providers: ["auth"],
      auth: authPresets.admin,
    });

    await waitFor(() => {
      expect(mockUseFileScopedChunksQuery).toHaveBeenCalledWith(
        "test.pdf",
        undefined,
      );
    });
  });

  it("preserves empty string from q param (line 21)", async () => {
    setMockLocation({
      pathname: "/knowledge/chunks",
      searchParams: { filename: "test.pdf", q: "" },
    });

    mockUseFileScopedChunksQuery.mockReturnValue({
      file: { filename: "test.pdf", chunks: [] },
      isFetching: false,
    });

    const { default: ProtectedChunksPage } = await import("./page");

    renderWithProviders(<ProtectedChunksPage />, {
      providers: ["auth"],
      auth: authPresets.admin,
    });

    await waitFor(() => {
      expect(mockUseFileScopedChunksQuery).toHaveBeenCalledWith("test.pdf", "");
    });
  });
});
