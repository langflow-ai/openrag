"use client";

import {
  Building2,
  Cloud,
  FileText,
  HardDrive,
  Loader2,
  Search,
  Trash2,
  Edit,
  RefreshCw,
} from "lucide-react";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { SiGoogledrive } from "react-icons/si";
import { TbBrandOnedrive } from "react-icons/tb";
import { FaEllipsisVertical } from "react-icons/fa6";
import { useQueryClient } from "@tanstack/react-query";
import { ProtectedRoute } from "@/components/protected-route";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { DeleteConfirmationDialog } from "../../../components/confirmation-dialog";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useTask } from "@/contexts/task-context";
import { type File, useGetSearchQuery } from "../api/queries/useGetSearchQuery";
import { KnowledgeDropdown } from "@/components/knowledge-dropdown";

// Function to get the appropriate icon for a connector type
function getSourceIcon(connectorType?: string) {
  switch (connectorType) {
    case "google_drive":
      return <SiGoogledrive className="h-4 w-4 text-foreground" />;
    case "onedrive":
      return <TbBrandOnedrive className="h-4 w-4 text-foreground" />;
    case "sharepoint":
      return <Building2 className="h-4 w-4 text-foreground" />;
    case "s3":
      return <Cloud className="h-4 w-4 text-foreground" />;
    default:
      return <HardDrive className="h-4 w-4 text-muted-foreground" />;
  }
}

function SearchPage() {
  const { isMenuOpen } = useTask();
  const { parsedFilterData, isPanelOpen } = useKnowledgeFilter();
  const [query, setQuery] = useState("");
  const [queryInputText, setQueryInputText] = useState("");
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);

  // Delete state
  const [selectedDocuments, setSelectedDocuments] = useState<Set<string>>(
    new Set()
  );
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{
    type: "bulk" | "single";
    filenames: string[];
  } | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0); // eslint-disable-line @typescript-eslint/no-unused-vars

  const queryClient = useQueryClient();

  const { data = [], isFetching } = useGetSearchQuery(query, parsedFilterData);

  // Use refs to access current values in event handler
  const currentQueryRef = useRef(query);
  const currentParsedFilterRef = useRef(parsedFilterData);
  const currentDataRef = useRef(data);

  currentQueryRef.current = query;
  currentParsedFilterRef.current = parsedFilterData;
  currentDataRef.current = data;

  // Update query when global filter changes
  useEffect(() => {
    if (parsedFilterData?.query) {
      setQueryInputText(parsedFilterData.query);
    }
  }, [parsedFilterData]);

  // Listen for knowledge updates from other sources (uploads, ingestion, etc.)
  useEffect(() => {
    const handleKnowledgeUpdate = async () => {
      // Get the current effective query that matches what the UI is showing (using refs to get current values)
      const currentEffectiveQuery =
        currentQueryRef.current || currentParsedFilterRef.current?.query || "*";

      // Be very aggressive about clearing the cache and refetching
      queryClient.removeQueries({
        queryKey: ["search"],
        exact: false,
      });

      // Force an immediate refetch of the current query
      await queryClient.refetchQueries({
        queryKey: ["search", currentEffectiveQuery],
        exact: true,
      });

      // Also trigger a state change to force re-render (backup plan)
      setRefreshTrigger(prev => prev + 1);
    };

    window.addEventListener("knowledgeUpdated", handleKnowledgeUpdate);

    return () => {
      window.removeEventListener("knowledgeUpdated", handleKnowledgeUpdate);
    };
  }, [queryClient]); // Only depend on queryClient which is stable

  const handleSearch = useCallback(
    (e?: FormEvent<HTMLFormElement>) => {
      if (e) e.preventDefault();
      if (query.trim() === queryInputText.trim()) {
        // If same query, invalidate cache to ensure fresh data
        const effectiveQuery =
          currentQueryRef.current ||
          currentParsedFilterRef.current?.query ||
          "*";
        queryClient.invalidateQueries({
          queryKey: ["search", effectiveQuery],
          exact: true,
        });
        return;
      }
      setQuery(queryInputText);
    },
    [queryInputText, query, queryClient]
  );

  // Delete handlers
  const handleBulkDelete = () => {
    const filenames = Array.from(selectedDocuments);
    setDeleteTarget({
      type: "bulk",
      filenames,
    });
    setDeleteDialogOpen(true);
  };

  const handleSingleDelete = (filename: string) => {
    setDeleteTarget({
      type: "single",
      filenames: [filename],
    });
    setDeleteDialogOpen(true);
    setOpenDropdown(null); // Close the dropdown
  };

  const handleRename = (filename: string) => {
    setOpenDropdown(null); // Close the dropdown
    alert(`Rename functionality not implemented yet for ${filename}`);
  };

  const handleSync = (filename: string) => {
    setOpenDropdown(null); // Close the dropdown
    alert(`Sync functionality not implemented yet for ${filename}`);
  };

  const performDelete = async () => {
    if (!deleteTarget) return;

    setIsDeleting(true);

    // Use the same effective query normalization as the search hook (using current refs)
    const effectiveQuery =
      currentQueryRef.current || currentParsedFilterRef.current?.query || "*";

    // Store the original data before optimistic update
    const originalData =
      queryClient.getQueryData<File[]>(["search", effectiveQuery]) || [];
    const filesToDelete = new Set(deleteTarget.filenames);

    // Optimistically update the UI - immediately filter out the files being deleted
    queryClient.setQueryData<File[]>(["search", effectiveQuery], oldData => {
      if (!oldData) return [];
      return oldData.filter(file => !filesToDelete.has(file.filename));
    });

    try {
      // Delete documents by filename (since we only have filenames, not document IDs)
      const filenames = deleteTarget.filenames;
      const results = [];
      let successCount = 0;
      const failedDeletes: string[] = [];

      for (const filename of filenames) {
        try {
          const response = await fetch("/api/documents/delete-by-filename", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              filename: filename,
            }),
          });

          if (response.ok) {
            const result = await response.json();
            results.push({ filename, success: true, ...result });
            successCount++;
          } else {
            const error = await response.json();
            results.push({ filename, success: false, error: error.error });
            failedDeletes.push(filename);
          }
        } catch (error) {
          results.push({ filename, success: false, error: String(error) });
          failedDeletes.push(filename);
        }
      }

      // Log results for user feedback
      console.info(`Deleted ${successCount}/${filenames.length} documents`);

      // If any deletes failed, restore the failed items to the UI
      if (failedDeletes.length > 0) {
        console.warn(
          `Failed to delete ${failedDeletes.length} documents:`,
          failedDeletes
        );

        // Restore failed items using the original data
        queryClient.setQueryData<File[]>(
          ["search", effectiveQuery],
          currentData => {
            if (!currentData) return originalData;

            const failedSet = new Set(failedDeletes);
            const restoredItems = originalData.filter(file =>
              failedSet.has(file.filename)
            );

            // Merge current optimistically updated data with restored failed items
            return [...currentData, ...restoredItems];
          }
        );
      }
      // If all deletes succeeded, keep the optimistic update - no need to refetch

      // Clear selection
      setSelectedDocuments(new Set());
    } catch (error) {
      console.error("Delete failed:", error);
      // Restore the original data on complete failure
      queryClient.setQueryData<File[]>(
        ["search", effectiveQuery],
        originalData
      );
      // TODO: Add toast notification for error
    } finally {
      setIsDeleting(false);
      setDeleteDialogOpen(false);
      setDeleteTarget(null);
    }
  };

  const toggleDocumentSelection = (filename: string) => {
    const newSelection = new Set(selectedDocuments);
    if (newSelection.has(filename)) {
      newSelection.delete(filename);
    } else {
      newSelection.add(filename);
    }
    setSelectedDocuments(newSelection);
  };

  const selectAllDocuments = () => {
    const allFilenames = new Set(fileResults.map(file => file.filename));
    setSelectedDocuments(allFilenames);
  };

  const clearSelection = () => {
    setSelectedDocuments(new Set());
  };

  const fileResults = data as File[];

  return (
    <div
      className={`fixed inset-0 md:left-72 top-[53px] flex flex-col transition-all duration-300 ${
        isMenuOpen && isPanelOpen
          ? "md:right-[704px]"
          : // Both open: 384px (menu) + 320px (KF panel)
          isMenuOpen
          ? "md:right-96"
          : // Only menu open: 384px
          isPanelOpen
          ? "md:right-80"
          : // Only KF panel open: 320px
            "md:right-6" // Neither open: 24px
      }`}
    >
      <div className="flex-1 flex flex-col min-h-0 px-6 py-6">
        {/* Search Input Area */}
        <div className="flex-shrink-0 mb-6">
          <div className="flex items-center gap-2 mb-5 justify-between">
            <span className="text-xl font-semibold text-primary">
              Knowledge Project
            </span>
            <KnowledgeDropdown variant="button" />
          </div>
          <form onSubmit={handleSearch} className="flex gap-3">
            <div className="lg:w-1/2 w-full">
              <Input
                name="search-query"
                id="search-query"
                type="text"
                defaultValue={parsedFilterData?.query}
                value={queryInputText}
                onChange={e => setQueryInputText(e.target.value)}
                placeholder="Search your documents..."
                className="flex-2 bg-muted/20 rounded-lg border border-border/50 px-4 py-3 h-12 focus-visible:ring-1 focus-visible:ring-ring"
              />
            </div>
            <Button
              type="submit"
              variant="secondary"
              className="rounded-lg h-12 w-12 p-0 flex-shrink-0"
            >
              {isFetching ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
            </Button>
            <Button
              variant="secondary"
              className="rounded-lg h-12 px-4 flex items-center gap-2 hover:bg-secondary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              onClick={() => alert("Sync not implemented yet")}
            >
              Sync
            </Button>

            <Button
              variant="destructive"
              onClick={handleBulkDelete}
              disabled={selectedDocuments.size === 0}
              className="rounded-lg h-12 px-4 flex items-center gap-2 hover:bg-destructive/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Delete
            </Button>
          </form>
        </div>

        {/* Results Area */}
        <div className="flex-1 overflow-y-auto">
          <div className="space-y-4">
            {fileResults.length === 0 && !isFetching ? (
              <div className="text-center py-12">
                <Search className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                <p className="text-lg text-muted-foreground">
                  No documents found
                </p>
                <p className="text-sm text-muted-foreground/70 mt-2">
                  Try adjusting your search terms
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Results Count and Bulk Actions */}
                <div className="mb-4 space-y-4">
                  <div className="text-sm text-muted-foreground">
                    {fileResults.length} file
                    {fileResults.length !== 1 ? "s" : ""} found
                  </div>
                </div>

                {/* Results Display */}
                <div
                  className={isFetching ? "opacity-50 pointer-events-none" : ""}
                >
                  {selectedFile ? (
                    // Show chunks for selected file
                    <>
                      <div className="flex items-center gap-2 mb-4">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setSelectedFile(null)}
                        >
                          ← Back to files
                        </Button>
                        <span className="text-sm text-muted-foreground">
                          Chunks from {selectedFile}
                        </span>
                      </div>
                      {fileResults
                        .filter(file => file.filename === selectedFile)
                        .flatMap(file => file.chunks)
                        .map((chunk, index) => (
                          <div
                            key={chunk.filename + index}
                            className="bg-muted/20 rounded-lg p-4 border border-border/50"
                          >
                            <div className="flex items-center justify-between mb-2">
                              <div className="flex items-center gap-2">
                                <FileText className="h-4 w-4 text-blue-400" />
                                <span className="font-medium truncate">
                                  {chunk.filename}
                                </span>
                              </div>
                              <span className="text-xs text-green-400 bg-green-400/20 px-2 py-1 rounded">
                                {chunk.score.toFixed(2)}
                              </span>
                            </div>
                            <div className="text-sm text-muted-foreground mb-2">
                              {chunk.mimetype} • Page {chunk.page}
                            </div>
                            <p className="text-sm text-foreground/90 leading-relaxed">
                              {chunk.text}
                            </p>
                          </div>
                        ))}
                    </>
                  ) : (
                    // Show files table
                    <div className="bg-muted/20 rounded-lg border border-border/50 overflow-x-auto">
                      <table className="w-full min-w-[800px]">
                        <thead>
                          <tr className="border-b border-border/50 bg-muted/10">
                            <th className="text-center p-3 text-sm font-medium text-muted-foreground pl-5 w-12">
                              <Checkbox
                                className="w-4 h-4 flex"
                                checked={
                                  selectedDocuments.size > 0 &&
                                  selectedDocuments.size ===
                                    new Set(fileResults.map(f => f.filename))
                                      .size
                                }
                                onCheckedChange={checked => {
                                  if (checked) {
                                    selectAllDocuments();
                                  } else {
                                    clearSelection();
                                  }
                                }}
                                onClick={e => e.stopPropagation()}
                              />
                            </th>
                            <th className="text-left p-3 text-sm font-medium text-muted-foreground min-w-[200px] max-w-[300px]">
                              Source
                            </th>
                            <th className="text-center p-3 text-sm font-medium text-muted-foreground w-32">
                              Type
                            </th>
                            <th className="text-center p-3 text-sm font-medium text-muted-foreground w-20">
                              Size
                            </th>
                            <th className="text-center p-3 text-sm font-medium text-muted-foreground w-20">
                              Chunks
                            </th>
                            <th className="text-center p-3 text-sm font-medium text-muted-foreground w-20">
                              Score
                            </th>

                            <th className="text-center p-3 text-sm font-medium text-muted-foreground w-12" />
                          </tr>
                        </thead>
                        <tbody>
                          {fileResults.map(file => (
                            <tr
                              key={file.filename}
                              className="border-b border-border/30 hover:bg-muted/20 transition-colors"
                            >
                              <td className="pl-5 w-12">
                                <div
                                  className="w-4 h-4 cursor-pointer group relative flex items-center justify-center"
                                  onClick={() =>
                                    toggleDocumentSelection(file.filename)
                                  }
                                >
                                  {selectedDocuments.has(file.filename) ? (
                                    <Checkbox
                                      checked={true}
                                      onCheckedChange={() =>
                                        toggleDocumentSelection(file.filename)
                                      }
                                      onClick={e => e.stopPropagation()}
                                    />
                                  ) : (
                                    <>
                                      <div className="group-hover:opacity-0 transition-opacity duration-200">
                                        {getSourceIcon(file.connector_type)}
                                      </div>
                                      <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex items-center justify-center">
                                        <Checkbox
                                          checked={false}
                                          onCheckedChange={() =>
                                            toggleDocumentSelection(
                                              file.filename
                                            )
                                          }
                                          onClick={e => e.stopPropagation()}
                                        />
                                      </div>
                                    </>
                                  )}
                                </div>
                              </td>
                              <td
                                className="p-3 cursor-pointer min-w-[200px] max-w-[300px]"
                                onClick={() => setSelectedFile(file.filename)}
                              >
                                <div className="flex items-center">
                                  <span
                                    className="font-medium truncate"
                                    title={file.filename}
                                  >
                                    {file.filename}
                                  </span>
                                </div>
                              </td>
                              <td
                                className="p-3 text-center text-sm text-muted-foreground cursor-pointer w-32"
                                onClick={() => setSelectedFile(file.filename)}
                              >
                                <span className="truncate block">
                                  {file.mimetype}
                                </span>
                              </td>
                              <td
                                className="p-3 text-center text-sm text-muted-foreground cursor-pointer w-20"
                                onClick={() => setSelectedFile(file.filename)}
                              >
                                {file.size
                                  ? `${Math.round(file.size / 1024)} KB`
                                  : "—"}
                              </td>
                              <td
                                className="p-3 text-center text-sm text-muted-foreground cursor-pointer w-20"
                                onClick={() => setSelectedFile(file.filename)}
                              >
                                {file.chunkCount}
                              </td>
                              <td
                                className="p-3 text-center cursor-pointer w-20"
                                onClick={() => setSelectedFile(file.filename)}
                              >
                                <span className="text-xs text-green-400 bg-green-400/20 px-2 py-1 rounded">
                                  {file.avgScore.toFixed(2)}
                                </span>
                              </td>

                              <td className="p-3 text-center text-sm text-muted-foreground w-12">
                                <Popover
                                  open={openDropdown === file.filename}
                                  onOpenChange={open =>
                                    setOpenDropdown(open ? file.filename : null)
                                  }
                                >
                                  <PopoverTrigger asChild>
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      onClick={e => {
                                        e.stopPropagation();
                                      }}
                                    >
                                      <FaEllipsisVertical className="h-4 w-4" />
                                    </Button>
                                  </PopoverTrigger>
                                  <PopoverContent
                                    className="w-40 p-0"
                                    align="end"
                                  >
                                    <div className="py-1">
                                      <button
                                        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-muted/50 transition-colors"
                                        onClick={() =>
                                          handleRename(file.filename)
                                        }
                                      >
                                        <Edit className="h-4 w-4" />
                                        <span>Rename</span>
                                      </button>
                                      <button
                                        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-muted/50 transition-colors"
                                        onClick={() =>
                                          handleSync(file.filename)
                                        }
                                      >
                                        <RefreshCw className="h-4 w-4" />
                                        <span>Sync</span>
                                      </button>
                                      <button
                                        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-muted/50 transition-colors"
                                        onClick={() =>
                                          handleSingleDelete(file.filename)
                                        }
                                      >
                                        <Trash2 className="h-4 w-4 text-destructive" />
                                        <span>Delete</span>
                                      </button>
                                    </div>
                                  </PopoverContent>
                                </Popover>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Delete Confirmation Dialog */}
      <DeleteConfirmationDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title={
          deleteTarget?.type === "single"
            ? `Delete "${deleteTarget.filenames[0]}"?`
            : `Delete ${deleteTarget?.filenames?.length || 0} documents?`
        }
        description={
          deleteTarget?.type === "single"
            ? `Are you sure you want to delete "${deleteTarget.filenames[0]}"? This action cannot be undone and will remove all associated chunks.`
            : `Are you sure you want to delete ${
                deleteTarget?.filenames?.length || 0
              } selected documents? This action cannot be undone and will remove all associated chunks.`
        }
        confirmText={
          deleteTarget?.type === "single"
            ? "Delete File"
            : "Delete All Selected"
        }
        onConfirm={performDelete}
        isLoading={isDeleting}
        variant="destructive"
      />
    </div>
  );
}

export default function ProtectedSearchPage() {
  return (
    <ProtectedRoute>
      <SearchPage />
    </ProtectedRoute>
  );
}
