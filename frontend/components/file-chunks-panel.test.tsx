import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, waitFor } from "@/test-utils/render";
import { FileChunksPanel } from "./file-chunks-panel";

const mockUseFileScopedChunksQuery = vi.fn();
vi.mock("@/app/api/queries/useFileScopedChunksQuery", () => ({
  useFileScopedChunksQuery: (filename: string, searchQuery?: string) =>
    mockUseFileScopedChunksQuery(filename, searchQuery),
}));

describe("FileChunksPanel - searchQuery prop forwarding (line 175)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("passes searchQuery prop to useFileScopedChunksQuery", async () => {
    mockUseFileScopedChunksQuery.mockReturnValue({
      file: { filename: "test.pdf", chunks: [] },
      isFetching: false,
    });

    renderWithProviders(
      <FileChunksPanel filename="test.pdf" searchQuery="test query" />,
      {
        providers: ["knowledgeFilter"],
      },
    );

    // Line 175: const { file, isFetching } = useFileScopedChunksQuery(filename, searchQuery);
    await waitFor(() => {
      expect(mockUseFileScopedChunksQuery).toHaveBeenCalledWith(
        "test.pdf",
        "test query",
      );
    });
  });

  it("passes undefined when searchQuery prop is not provided", async () => {
    mockUseFileScopedChunksQuery.mockReturnValue({
      file: { filename: "test.pdf", chunks: [] },
      isFetching: false,
    });

    renderWithProviders(<FileChunksPanel filename="test.pdf" />, {
      providers: ["knowledgeFilter"],
    });

    await waitFor(() => {
      expect(mockUseFileScopedChunksQuery).toHaveBeenCalledWith(
        "test.pdf",
        undefined,
      );
    });
  });

  it("passes empty string when searchQuery prop is empty", async () => {
    mockUseFileScopedChunksQuery.mockReturnValue({
      file: { filename: "test.pdf", chunks: [] },
      isFetching: false,
    });

    renderWithProviders(
      <FileChunksPanel filename="test.pdf" searchQuery="" />,
      {
        providers: ["knowledgeFilter"],
      },
    );

    await waitFor(() => {
      expect(mockUseFileScopedChunksQuery).toHaveBeenCalledWith("test.pdf", "");
    });
  });
});
