import { Check, Funnel, Loader2, Plus, X } from "lucide-react";
import TextareaAutosize from "react-textarea-autosize";
import { forwardRef, useImperativeHandle, useRef } from "react";
import { filterAccentClasses } from "@/components/knowledge-filter-panel";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/ui/popover";
import type { KnowledgeFilterData } from "../types";
import { FilterColor } from "@/components/filter-icon-popover";

export interface ChatInputHandle {
  focusInput: () => void;
  clickFileInput: () => void;
}

interface ChatInputProps {
  input: string;
  loading: boolean;
  isUploading: boolean;
  selectedFilter: KnowledgeFilterData | null;
  isFilterHighlighted: boolean;
  isFilterDropdownOpen: boolean;
  availableFilters: KnowledgeFilterData[];
  filterSearchTerm: string;
  selectedFilterIndex: number;
  anchorPosition: { x: number; y: number } | null;
  textareaHeight: number;
  parsedFilterData: { color?: FilterColor } | null;
  onSubmit: (e: React.FormEvent) => void;
  onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onHeightChange: (height: number) => void;
  onFilterSelect: (filter: KnowledgeFilterData | null) => void;
  onAtClick: () => void;
  onFilePickerChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onFilePickerClick: () => void;
  setSelectedFilter: (filter: KnowledgeFilterData | null) => void;
  setIsFilterHighlighted: (highlighted: boolean) => void;
  setIsFilterDropdownOpen: (open: boolean) => void;
}

export const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>((
  {
    input,
    loading,
    isUploading,
    selectedFilter,
    isFilterHighlighted,
    isFilterDropdownOpen,
    availableFilters,
    filterSearchTerm,
    selectedFilterIndex,
    anchorPosition,
    textareaHeight,
    parsedFilterData,
    onSubmit,
    onChange,
    onKeyDown,
    onHeightChange,
    onFilterSelect,
    onAtClick,
    onFilePickerChange,
    onFilePickerClick,
    setSelectedFilter,
    setIsFilterHighlighted,
    setIsFilterDropdownOpen,
  },
  ref
) => {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useImperativeHandle(ref, () => ({
    focusInput: () => {
      inputRef.current?.focus();
    },
    clickFileInput: () => {
      fileInputRef.current?.click();
    },
  }));

  return (
    <div className="pb-8 pt-4 flex px-6">
      <div className="w-full">
        <form onSubmit={onSubmit} className="relative">
          <div className="relative w-full bg-muted/20 rounded-lg border border-border/50 focus-within:ring-1 focus-within:ring-ring">
            {selectedFilter && (
              <div className="flex items-center gap-2 px-4 pt-3 pb-1">
                <span
                  className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium transition-colors ${
                    filterAccentClasses[parsedFilterData?.color || "zinc"]
                  }`}
                >
                  @filter:{selectedFilter.name}
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedFilter(null);
                      setIsFilterHighlighted(false);
                    }}
                    className="ml-1 rounded-full p-0.5"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              </div>
            )}
            <div
              className="relative"
              style={{ height: `${textareaHeight + 60}px` }}
            >
              <TextareaAutosize
                ref={inputRef}
                value={input}
                onChange={onChange}
                onKeyDown={onKeyDown}
                onHeightChange={onHeightChange}
                maxRows={7}
                minRows={2}
                placeholder="Type to ask a question..."
                disabled={loading}
                className={`w-full bg-transparent px-4 ${
                  selectedFilter ? "pt-2" : "pt-4"
                } focus-visible:outline-none resize-none`}
                rows={2}
              />
              {/* Safe area at bottom for buttons */}
              <div
                className="absolute bottom-0 left-0 right-0 bg-transparent pointer-events-none"
                style={{ height: "60px" }}
              />
            </div>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            onChange={onFilePickerChange}
            className="hidden"
            accept=".pdf,.doc,.docx,.txt,.md,.rtf,.odt"
          />
          <Button
            type="button"
            variant="outline"
            size="iconSm"
            className="absolute bottom-3 left-3 h-8 w-8 p-0 rounded-full hover:bg-muted/50"
            onMouseDown={e => {
              e.preventDefault();
            }}
            onClick={onAtClick}
            data-filter-button
          >
            <Funnel className="h-4 w-4" />
          </Button>
          <Popover
            open={isFilterDropdownOpen}
            onOpenChange={open => {
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
              onOpenAutoFocus={e => {
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
                        onClick={() => onFilterSelect(null)}
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
                    {availableFilters
                      .filter(filter =>
                        filter.name
                          .toLowerCase()
                          .includes(filterSearchTerm.toLowerCase())
                      )
                      .map((filter, index) => (
                        <button
                          key={filter.id}
                          type="button"
                          onClick={() => onFilterSelect(filter)}
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
                    {availableFilters.filter(filter =>
                      filter.name
                        .toLowerCase()
                        .includes(filterSearchTerm.toLowerCase())
                    ).length === 0 &&
                      filterSearchTerm && (
                        <div className="px-2 py-3 text-sm text-muted-foreground">
                          No filters match &quot;{filterSearchTerm}&quot;
                        </div>
                      )}
                  </>
                )}
              </div>
            </PopoverContent>
          </Popover>
          <Button
            type="button"
            variant="outline"
            size="iconSm"
            onClick={onFilePickerClick}
            disabled={isUploading}
            className="absolute bottom-3 left-12 h-8 w-8 p-0 rounded-full hover:bg-muted/50"
          >
            <Plus className="h-4 w-4" />
          </Button>
          <Button
            type="submit"
            disabled={!input.trim() || loading}
            className="absolute bottom-3 right-3 rounded-lg h-10 px-4"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Send"}
          </Button>
        </form>
      </div>
    </div>
  );
});

ChatInput.displayName = "ChatInput";
