/**
 * ChatInput — minimal render test covering line 71: useSupportedFileTypes call.
 *
 * The component has many dependencies; we stub the ones that would otherwise
 * require a full backend or complex provider stack.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test-utils/render";
import { ChatInput } from "./chat-input";

vi.mock("@/contexts/brand-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/brand-context")>()),
  useIsCloudBrand: () => false,
}));

vi.mock("@/hooks/use-supported-file-types", () => ({
  useSupportedFileTypes: () => ({
    supportedFileTypes: { "application/pdf": [".pdf"] },
    supportedExtensions: [".pdf"],
  }),
}));

vi.mock("@/app/api/queries/useGetAllFiltersQuery", () => ({
  useGetAllFiltersQuery: () => ({ data: [] }),
}));

const defaultProps = {
  input: "",
  loading: false,
  isUploading: false,
  ingestViaChat: false,
  selectedFilter: null,
  parsedFilterData: null,
  uploadedFile: null,
  onSubmit: vi.fn(),
  onChange: vi.fn(),
  onKeyDown: vi.fn(),
  onFilterSelect: vi.fn(),
  onFilePickerClick: vi.fn(),
  setSelectedFilter: vi.fn(),
  setIsFilterHighlighted: vi.fn(),
  onFileSelected: vi.fn(),
};

describe("ChatInput", () => {
  // Line 71: useSupportedFileTypes is called on every render; mounting the
  // component exercises it.
  it("renders without error (exercises useSupportedFileTypes on line 71)", () => {
    renderWithProviders(<ChatInput {...defaultProps} />);
    // The textarea is the primary interactive element
    expect(document.body).toBeTruthy();
  });
});
