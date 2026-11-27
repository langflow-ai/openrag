/**
 * ChatInput — minimal render test covering line 71: useSupportedFileTypes call.
 *
 * The component has many dependencies; we stub the ones that would otherwise
 * require a full backend or complex provider stack.
 */
import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test-utils/render";
import type { KnowledgeFilterData } from "../_types/types";
import { ChatInput } from "./chat-input";
import { TABLE_ONLY_FILTER_TOOLTIP } from "./selected-knowledge-filter";

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

const { filtersQuery } = vi.hoisted(() => ({
  filtersQuery: vi.fn(() => ({ data: [] as KnowledgeFilterData[] })),
}));

vi.mock("@/app/api/queries/useGetAllFiltersQuery", () => ({
  useGetAllFiltersQuery: filtersQuery,
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

const docsFilter: KnowledgeFilterData = {
  id: "docs",
  name: "Docs",
  description: "Documentation",
  query_data: JSON.stringify({ filters: { data_sources: ["docs.md"] } }),
  owner: "me",
  created_at: "",
  updated_at: "",
};

function chatBox() {
  return screen.getByPlaceholderText<HTMLTextAreaElement>("Ask a question...");
}

describe("ChatInput", () => {
  // Line 71: useSupportedFileTypes is called on every render; mounting the
  // component exercises it.
  it("renders without error (exercises useSupportedFileTypes on line 71)", () => {
    renderWithProviders(<ChatInput {...defaultProps} />);
    // The textarea is the primary interactive element
    expect(document.body).toBeTruthy();
  });

  it("forwards Enter so the parent can submit", () => {
    const onKeyDown = vi.fn();
    renderWithProviders(<ChatInput {...defaultProps} onKeyDown={onKeyDown} />);

    fireEvent.keyDown(chatBox(), { key: "Enter" });

    expect(onKeyDown).toHaveBeenCalledOnce();
  });

  it("does not forward Enter that confirms an IME candidate", () => {
    const onKeyDown = vi.fn();
    renderWithProviders(<ChatInput {...defaultProps} onKeyDown={onKeyDown} />);
    const box = chatBox();

    fireEvent.keyDown(box, { key: "Enter", isComposing: true });
    fireEvent.keyDown(box, { key: "Enter", keyCode: 229 });

    expect(onKeyDown).not.toHaveBeenCalled();
  });

  it("does not forward the Enter Safari fires immediately after compositionend", () => {
    const onKeyDown = vi.fn();
    renderWithProviders(<ChatInput {...defaultProps} onKeyDown={onKeyDown} />);
    const box = chatBox();

    fireEvent.compositionStart(box);
    fireEvent.compositionEnd(box);
    const cancelled = fireEvent.keyDown(box, { key: "Enter" });

    expect(onKeyDown).not.toHaveBeenCalled();
    expect(cancelled).toBe(false);
  });

  it("forwards a second Enter that lands inside the IME confirmation window", () => {
    let now = 1_000;
    const nowSpy = vi.spyOn(performance, "now").mockImplementation(() => now);
    const onKeyDown = vi.fn();
    renderWithProviders(<ChatInput {...defaultProps} onKeyDown={onKeyDown} />);
    const box = chatBox();

    fireEvent.compositionEnd(box);
    now = 1_010;
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.keyDown(box, { key: "Enter" });

    expect(onKeyDown).toHaveBeenCalledOnce();
    nowSpy.mockRestore();
  });

  it("forwards Enter again once the IME confirmation window has passed", () => {
    let now = 1_000;
    const nowSpy = vi.spyOn(performance, "now").mockImplementation(() => now);
    const onKeyDown = vi.fn();
    renderWithProviders(<ChatInput {...defaultProps} onKeyDown={onKeyDown} />);
    const box = chatBox();

    fireEvent.compositionEnd(box);
    now = 1_050;
    fireEvent.keyDown(box, { key: "Enter" });

    expect(onKeyDown).toHaveBeenCalledOnce();
    nowSpy.mockRestore();
  });

  it("forwards Enter after blur clears a finished composition", () => {
    const onKeyDown = vi.fn();
    renderWithProviders(<ChatInput {...defaultProps} onKeyDown={onKeyDown} />);
    const box = chatBox();

    fireEvent.compositionEnd(box);
    fireEvent.blur(box);
    fireEvent.keyDown(box, { key: "Enter" });

    expect(onKeyDown).toHaveBeenCalledOnce();
  });

  it("does not select a knowledge filter when Enter confirms an IME candidate", () => {
    filtersQuery.mockReturnValue({ data: [docsFilter] });
    const onFilterSelect = vi.fn();
    const props = { ...defaultProps, onFilterSelect, input: "" };
    const { rerender } = renderWithProviders(<ChatInput {...props} />);
    const box = chatBox();

    fireEvent.change(box, { target: { value: "@" } });
    rerender(<ChatInput {...props} input="@" />);
    box.selectionStart = 1;

    fireEvent.keyDown(box, { key: "Enter", isComposing: true });
    expect(onFilterSelect).not.toHaveBeenCalled();

    fireEvent.keyDown(box, { key: "Enter" });
    expect(onFilterSelect).toHaveBeenCalledWith(docsFilter);
  });

  it("does not select a knowledge filter when Space cycles an IME candidate", () => {
    filtersQuery.mockReturnValue({ data: [docsFilter] });
    const onFilterSelect = vi.fn();
    const props = { ...defaultProps, onFilterSelect, input: "" };
    const { rerender } = renderWithProviders(<ChatInput {...props} />);
    const box = chatBox();

    fireEvent.change(box, { target: { value: "@" } });
    rerender(<ChatInput {...props} input="@" />);
    box.selectionStart = 1;

    fireEvent.keyDown(box, { key: " ", isComposing: true });
    expect(onFilterSelect).not.toHaveBeenCalled();

    fireEvent.keyDown(box, { key: " " });
    expect(onFilterSelect).toHaveBeenCalledWith(docsFilter);
  });

  it("lists table-only filters as disabled with an explanation", async () => {
    const tableOnly: KnowledgeFilterData = {
      ...docsFilter,
      id: "labs",
      name: "Labs",
      description: "",
      query_data: JSON.stringify({
        query: "labs.pdf",
        filters: { data_sources: ["*"], document_types: ["*"] },
      }),
    };
    filtersQuery.mockReturnValue({ data: [tableOnly, docsFilter] });
    const onFilterSelect = vi.fn();
    const props = { ...defaultProps, onFilterSelect, input: "" };
    const { rerender } = renderWithProviders(<ChatInput {...props} />);
    const box = chatBox();

    fireEvent.change(box, { target: { value: "@" } });
    rerender(<ChatInput {...props} input="@" />);

    expect(await screen.findByText("Knowledge table only")).toBeInTheDocument();
    expect(screen.getByRole("separator")).toBeInTheDocument();
    const labs = screen.getByRole("button", { name: /labs/i });
    expect(labs).toBeDisabled();
    expect(labs).toHaveAccessibleDescription(TABLE_ONLY_FILTER_TOOLTIP);

    fireEvent.click(labs);
    expect(onFilterSelect).not.toHaveBeenCalled();

    // Keyboard selection skips the table-only filter listed first.
    box.selectionStart = 1;
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onFilterSelect).toHaveBeenCalledWith(docsFilter);
  });

  it("mutes the selected chip once its filter no longer restricts chat", () => {
    const edited: KnowledgeFilterData = {
      ...docsFilter,
      query_data: JSON.stringify({ filters: { data_sources: ["*"] } }),
    };
    renderWithProviders(
      <ChatInput {...defaultProps} selectedFilter={edited} />,
    );
    expect(
      screen.getByText("Docs", { selector: "[aria-description]" }),
    ).toHaveAttribute("aria-description", TABLE_ONLY_FILTER_TOOLTIP);
  });

  it("shows a scoped chip without the table-only note", () => {
    renderWithProviders(
      <ChatInput {...defaultProps} selectedFilter={docsFilter} />,
    );
    expect(screen.getByTestId("selected-knowledge-filter")).toHaveTextContent(
      "Docs",
    );
    expect(document.querySelector("[aria-description]")).toBeNull();
  });
});
