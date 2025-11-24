import { ArrowRight, Check, Funnel, Loader2, Plus } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import {
  forwardRef,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { useDropzone } from "react-dropzone";
import TextareaAutosize from "react-textarea-autosize";
import { toast } from "sonner";
import type { FilterColor } from "@/components/filter-icon-popover";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/ui/popover";
import { useFileDrag } from "@/hooks/use-file-drag";
import { cn } from "@/lib/utils";
import { useGetFiltersSearchQuery } from "../../api/queries/useGetFiltersSearchQuery";
import type { KnowledgeFilterData } from "../_types/types";
import { FilePreview } from "./file-preview";
import { SelectedKnowledgeFilter } from "./selected-knowledge-filter";

export interface ChatInputHandle {
  focusInput: () => void;
  clickFileInput: () => void;
}

interface ChatInputProps {
  input: string;
  loading: boolean;
  isUploading: boolean;
  selectedFilter: KnowledgeFilterData | null;
  parsedFilterData: { color?: FilterColor } | null;
  uploadedFile: File | null;
  onSubmit: (e: React.FormEvent) => void;
  onChange: (value: string) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onFilterSelect: (filter: KnowledgeFilterData | null) => void;
  onFilePickerClick: () => void;
  setSelectedFilter: (filter: KnowledgeFilterData | null) => void;
  setIsFilterHighlighted: (highlighted: boolean) => void;
  onFileSelected: (file: File | null) => void;
}

export const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(
  (
    {
      input,
      loading,
      isUploading,
      selectedFilter,
      parsedFilterData,
      uploadedFile,
      onSubmit,
      onChange,
      onKeyDown,
      onFilterSelect,
      onFilePickerClick,
      setSelectedFilter,
      setIsFilterHighlighted,
      onFileSelected,
    },
    ref,
  ) => {
    const inputRef = useRef<HTMLTextAreaElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [textareaHeight, setTextareaHeight] = useState(0);
    const isDragging = useFileDrag();

    // Internal state for filter dropdown
    const [isFilterDropdownOpen, setIsFilterDropdownOpen] = useState(false);
    const [filterSearchTerm, setFilterSearchTerm] = useState("");
    const [selectedFilterIndex, setSelectedFilterIndex] = useState(0);
    const [anchorPosition, setAnchorPosition] = useState<{
      x: number;
      y: number;
    } | null>(null);

    // Fetch filters using the query hook
    const { data: availableFilters = [] } = useGetFiltersSearchQuery(
      filterSearchTerm,
      20,
      { enabled: isFilterDropdownOpen },
    );

    // Filter available filters based on search term
    const filteredFilters = useMemo(() => {
      return availableFilters.filter((filter) =>
        filter.name.toLowerCase().includes(filterSearchTerm.toLowerCase()),
      );
    }, [availableFilters, filterSearchTerm]);

    const { getRootProps, getInputProps } = useDropzone({
      accept: {
        "application/pdf": [".pdf"],
        "application/msword": [".doc"],
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
          [".docx"],
        "text/markdown": [".md"],
      },
      maxFiles: 1,
      disabled: !isDragging,
      onDrop: (acceptedFiles, fileRejections) => {
        if (fileRejections.length > 0) {
          const message = fileRejections.at(0)?.errors.at(0)?.message;
          toast.error(message || "Failed to upload file");
          return;
        }
        onFileSelected(acceptedFiles[0]);
      },
    });

    useImperativeHandle(ref, () => ({
      focusInput: () => {
        inputRef.current?.focus();
      },
      clickFileInput: () => {
        fileInputRef.current?.click();
      },
    }));

    const handleFilePickerChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (files && files.length > 0) {
        onFileSelected(files[0]);
      } else {
        onFileSelected(null);
      }
    };

    const onAtClick = () => {
      if (!isFilterDropdownOpen) {
        setIsFilterDropdownOpen(true);
        setFilterSearchTerm("");
        setSelectedFilterIndex(0);

        // Get button position for popover anchoring
        const button = document.querySelector(
          "[data-filter-button]",
        ) as HTMLElement;
        if (button) {
          const rect = button.getBoundingClientRect();
          setAnchorPosition({
            x: rect.left + rect.width / 2,
            y: rect.top + rect.height / 2 - 12,
          });
        }
      } else {
        setIsFilterDropdownOpen(false);
        setAnchorPosition(null);
      }
    };

    const handleFilterSelect = (filter: KnowledgeFilterData | null) => {
      onFilterSelect(filter);

      // Remove the @searchTerm from the input
      const words = input.split(" ");
      const lastWord = words[words.length - 1];

      if (lastWord.startsWith("@")) {
        // Remove the @search term
        words.pop();
        onChange(words.join(" ") + (words.length > 0 ? " " : ""));
      }

      setIsFilterDropdownOpen(false);
      setFilterSearchTerm("");
      setSelectedFilterIndex(0);
    };

    const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const newValue = e.target.value;
      onChange(newValue); // Call parent's onChange with the string value

      // Find if there's an @ at the start of the last word
      const words = newValue.split(" ");
      const lastWord = words[words.length - 1];

      if (lastWord.startsWith("@")) {
        const searchTerm = lastWord.slice(1); // Remove the @
        setFilterSearchTerm(searchTerm);
        setSelectedFilterIndex(0);

        // Only set anchor position when @ is first detected (search term is empty)
        if (searchTerm === "") {
          const getCursorPosition = (textarea: HTMLTextAreaElement) => {
            // Create a hidden div with the same styles as the textarea
            const div = document.createElement("div");
            const computedStyle = getComputedStyle(textarea);

            // Copy all computed styles to the hidden div
            for (const style of computedStyle) {
              (div.style as unknown as Record<string, string>)[style] =
                computedStyle.getPropertyValue(style);
            }

            // Set the div to be hidden but not un-rendered
            div.style.position = "absolute";
            div.style.visibility = "hidden";
            div.style.whiteSpace = "pre-wrap";
            div.style.wordWrap = "break-word";
            div.style.overflow = "hidden";
            div.style.height = "auto";
            div.style.width = `${textarea.getBoundingClientRect().width}px`;

            // Get the text up to the cursor position
            const cursorPos = textarea.selectionStart || 0;
            const textBeforeCursor = textarea.value.substring(0, cursorPos);

            // Add the text before cursor
            div.textContent = textBeforeCursor;

            // Create a span to mark the end position
            const span = document.createElement("span");
            span.textContent = "|"; // Cursor marker
            div.appendChild(span);

            // Add the text after cursor to handle word wrapping
            const textAfterCursor = textarea.value.substring(cursorPos);
            div.appendChild(document.createTextNode(textAfterCursor));

            // Add the div to the document temporarily
            document.body.appendChild(div);

            // Get positions
            const inputRect = textarea.getBoundingClientRect();
            const divRect = div.getBoundingClientRect();
            const spanRect = span.getBoundingClientRect();

            // Calculate the cursor position relative to the input
            const x = inputRect.left + (spanRect.left - divRect.left);
            const y = inputRect.top + (spanRect.top - divRect.top);

            // Clean up
            document.body.removeChild(div);

            return { x, y };
          };

          const pos = getCursorPosition(e.target);
          setAnchorPosition(pos);
        }

        if (!isFilterDropdownOpen) {
          setIsFilterDropdownOpen(true);
        }
      } else if (isFilterDropdownOpen) {
        // Close dropdown if @ is no longer present
        setIsFilterDropdownOpen(false);
        setFilterSearchTerm("");
      }
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (isFilterDropdownOpen) {
        if (e.key === "Escape") {
          e.preventDefault();
          setIsFilterDropdownOpen(false);
          setFilterSearchTerm("");
          setSelectedFilterIndex(0);
          inputRef.current?.focus();
          return;
        }

        if (e.key === "ArrowDown") {
          e.preventDefault();
          setSelectedFilterIndex((prev) =>
            prev < filteredFilters.length - 1 ? prev + 1 : 0,
          );
          return;
        }

        if (e.key === "ArrowUp") {
          e.preventDefault();
          setSelectedFilterIndex((prev) =>
            prev > 0 ? prev - 1 : filteredFilters.length - 1,
          );
          return;
        }

        if (e.key === "Enter") {
          // Check if we're at the end of an @ mention
          const cursorPos = e.currentTarget.selectionStart || 0;
          const textBeforeCursor = input.slice(0, cursorPos);
          const words = textBeforeCursor.split(" ");
          const lastWord = words[words.length - 1];

          if (
            lastWord.startsWith("@") &&
            filteredFilters[selectedFilterIndex]
          ) {
            e.preventDefault();
            handleFilterSelect(filteredFilters[selectedFilterIndex]);
            return;
          }
        }

        if (e.key === " ") {
          // Select filter on space if we're typing an @ mention
          const cursorPos = e.currentTarget.selectionStart || 0;
          const textBeforeCursor = input.slice(0, cursorPos);
          const words = textBeforeCursor.split(" ");
          const lastWord = words[words.length - 1];

          if (
            lastWord.startsWith("@") &&
            filteredFilters[selectedFilterIndex]
          ) {
            e.preventDefault();
            handleFilterSelect(filteredFilters[selectedFilterIndex]);
            return;
          }
        }
      }

      // Pass through to parent onKeyDown for other key handling
      onKeyDown(e);
    };

    return (
      <div className="w-full">
        <form onSubmit={onSubmit} className="relative">
          {/* Outer container - flex-col to stack file preview above input */}
          <div
            {...getRootProps()}
            className={cn(
              "flex flex-col w-full p-2 rounded-xl border border-input transition-all",
              !isDragging &&
                "hover:[&:not(:focus-within)]:border-muted-foreground focus-within:border-foreground",
              isDragging && "border-dashed",
            )}
          >
            <input {...getInputProps()} />
            {/* File Preview Section - Always above */}
            <AnimatePresence>
              {uploadedFile && (
                <motion.div
                  initial={{ opacity: 0, height: 0, marginBottom: 0 }}
                  animate={{ opacity: 1, height: "auto", marginBottom: 8 }}
                  exit={{ opacity: 0, height: 0, marginBottom: 0 }}
                  className="overflow-hidden"
                >
                  <FilePreview
                    uploadedFile={uploadedFile}
                    onClear={() => {
                      onFileSelected(null);
                    }}
                    isUploading={isUploading}
                  />
                </motion.div>
              )}
            </AnimatePresence>
            <AnimatePresence>
              {isDragging && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 100 }}
                  exit={{ opacity: 0, height: 0 }}
                  className="overflow-hidden w-full flex flex-col items-center justify-center gap-2"
                >
                  <p className="text-md font-medium text-primary">
                    Add files to conversation
                  </p>
                  <p className="text-sm text-muted-foreground">
                    Text formats and image files.{" "}
                    <span className="font-semibold">10</span> files per chat,{" "}
                    <span className="font-semibold">150 MB</span> each.
                  </p>
                </motion.div>
              )}
            </AnimatePresence>
            {/* Main Input Container - flex-row or flex-col based on textarea height */}
            <div
              className={`relative flex w-full gap-2 ${
                textareaHeight > 40 ? "flex-col" : "flex-row items-center"
              }`}
            >
              {/* Filter + Textarea Section */}
              <div
                className={`flex items-center gap-2 ${textareaHeight > 40 ? "w-full" : "flex-1"}`}
              >
                {textareaHeight <= 40 &&
                  (selectedFilter ? (
                    <SelectedKnowledgeFilter
                      selectedFilter={selectedFilter}
                      parsedFilterData={parsedFilterData}
                      onClear={() => {
                        setSelectedFilter(null);
                        setIsFilterHighlighted(false);
                      }}
                    />
                  ) : (
                    <Button
                      type="button"
                      variant="ghost"
                      size="iconSm"
                      className="h-8 w-8 p-0 rounded-md hover:bg-muted/50"
                      onMouseDown={(e) => {
                        e.preventDefault();
                      }}
                      onClick={onAtClick}
                      data-filter-button
                    >
                      <Funnel className="h-4 w-4" />
                    </Button>
                  ))}
                <div
                  className="relative flex-1"
                  style={{ height: `${textareaHeight}px` }}
                >
                  <TextareaAutosize
                    ref={inputRef}
                    value={input}
                    onChange={handleChange}
                    onKeyDown={handleKeyDown}
                    onHeightChange={(height) => setTextareaHeight(height)}
                    maxRows={7}
                    autoComplete="off"
                    minRows={1}
                    placeholder="Ask a question..."
                    disabled={loading}
                    className={`w-full text-sm bg-transparent focus-visible:outline-none resize-none`}
                    rows={1}
                  />
                </div>
              </div>

              {/* Action Buttons Section */}
              <div
                className={`flex items-center gap-2 ${textareaHeight > 40 ? "justify-between w-full" : ""}`}
              >
                {textareaHeight > 40 &&
                  (selectedFilter ? (
                    <SelectedKnowledgeFilter
                      selectedFilter={selectedFilter}
                      parsedFilterData={parsedFilterData}
                      onClear={() => {
                        setSelectedFilter(null);
                        setIsFilterHighlighted(false);
                      }}
                    />
                  ) : (
                    <Button
                      type="button"
                      variant="ghost"
                      size="iconSm"
                      className="h-8 w-8 p-0 rounded-md hover:bg-muted/50"
                      onMouseDown={(e) => {
                        e.preventDefault();
                      }}
                      onClick={onAtClick}
                      data-filter-button
                    >
                      <Funnel className="h-4 w-4" />
                    </Button>
                  ))}
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="iconSm"
                    onClick={onFilePickerClick}
                    disabled={isUploading}
                    className="h-8 w-8 p-0 !rounded-md hover:bg-muted/50"
                  >
                    <Plus className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="default"
                    type="submit"
                    size="iconSm"
                    disabled={(!input.trim() && !uploadedFile) || loading}
                    className="!rounded-md h-8 w-8 p-0"
                  >
                    {loading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <ArrowRight className="h-4 w-4" />
                    )}
                  </Button>
                </div>
              </div>
            </div>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            onChange={handleFilePickerChange}
            className="hidden"
            accept=".pdf,.doc,.docx,.txt,.md,.rtf,.odt"
          />

          <Popover
            open={isFilterDropdownOpen}
            onOpenChange={(open) => {
              setIsFilterDropdownOpen(open);
            }}
          >
            {anchorPosition && (
              <PopoverAnchor
                asChild
                style={{
                  position: "fixed",
                  left: anchorPosition.x,
                  top: anchorPosition.y,
                  width: 1,
                  height: 1,
                  pointerEvents: "none",
                }}
              >
                <div />
              </PopoverAnchor>
            )}
            <PopoverContent
              className="w-64 p-2"
              side="top"
              align="start"
              sideOffset={6}
              alignOffset={-18}
              onOpenAutoFocus={(e) => {
                // Prevent auto focus on the popover content
                e.preventDefault();
                // Keep focus on the input
              }}
            >
              <div className="space-y-1">
                {filterSearchTerm && (
                  <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground">
                    Searching: @{filterSearchTerm}
                  </div>
                )}
                {availableFilters.length === 0 ? (
                  <div className="px-2 py-3 text-sm text-muted-foreground">
                    No knowledge filters available
                  </div>
                ) : (
                  <>
                    {!filterSearchTerm && (
                      <button
                        type="button"
                        onClick={() => handleFilterSelect(null)}
                        className={`w-full text-left px-2 py-2 text-sm rounded hover:bg-muted/50 flex items-center justify-between ${
                          selectedFilterIndex === -1 ? "bg-muted/50" : ""
                        }`}
                      >
                        <span>No knowledge filter</span>
                        {!selectedFilter && (
                          <Check className="h-4 w-4 shrink-0" />
                        )}
                      </button>
                    )}
                    {filteredFilters.map((filter, index) => (
                      <button
                        key={filter.id}
                        type="button"
                        onClick={() => handleFilterSelect(filter)}
                        className={`w-full overflow-hidden text-left px-2 py-2 gap-2 text-sm rounded hover:bg-muted/50 flex items-center justify-between ${
                          index === selectedFilterIndex ? "bg-muted/50" : ""
                        }`}
                      >
                        <div className="overflow-hidden">
                          <div className="font-medium truncate">
                            {filter.name}
                          </div>
                          {filter.description && (
                            <div className="text-xs text-muted-foreground truncate">
                              {filter.description}
                            </div>
                          )}
                        </div>
                        {selectedFilter?.id === filter.id && (
                          <Check className="h-4 w-4 shrink-0" />
                        )}
                      </button>
                    ))}
                    {filteredFilters.length === 0 && filterSearchTerm && (
                      <div className="px-2 py-3 text-sm text-muted-foreground">
                        No filters match &quot;{filterSearchTerm}&quot;
                      </div>
                    )}
                  </>
                )}
              </div>
            </PopoverContent>
          </Popover>
        </form>
      </div>
    );
  },
);

ChatInput.displayName = "ChatInput";
