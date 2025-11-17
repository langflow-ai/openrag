"use client";

import {
  EllipsisVertical,
  FileText,
  Library,
  MessageSquare,
  Plus,
  Settings2,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useDeleteSessionMutation } from "@/app/api/queries/useDeleteSessionMutation";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { type EndpointType, useChat } from "@/contexts/chat-context";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { FILES_REGEX } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { useLoadingStore } from "@/stores/loadingStore";
import { DeleteSessionModal } from "./delete-session-modal";
import { KnowledgeFilterList } from "./knowledge-filter-list";

// Re-export the types for backward compatibility
export interface RawConversation {
  response_id: string;
  title: string;
  endpoint: string;
  messages: Array<{
    role: string;
    content: string;
    timestamp?: string;
    response_id?: string;
  }>;
  created_at?: string;
  last_activity?: string;
  previous_response_id?: string;
  total_messages: number;
  [key: string]: unknown;
}

export interface ChatConversation {
  response_id: string;
  title: string;
  endpoint: EndpointType;
  messages: Array<{
    role: string;
    content: string;
    timestamp?: string;
    response_id?: string;
  }>;
  created_at?: string;
  last_activity?: string;
  previous_response_id?: string;
  total_messages: number;
  [key: string]: unknown;
}

interface NavigationProps {
  conversations?: ChatConversation[];
  isConversationsLoading?: boolean;
  onNewConversation?: () => void;
}

export function Navigation({
  conversations = [],
  isConversationsLoading = false,
  onNewConversation,
}: NavigationProps = {}) {
  const pathname = usePathname();
  const {
    endpoint,
    loadConversation,
    currentConversationId,
    setCurrentConversationId,
    startNewConversation,
    conversationDocs,
    conversationData,
    addConversationDoc,
    refreshConversations,
    placeholderConversation,
    setPlaceholderConversation,
    conversationLoaded,
  } = useChat();

  const { loading } = useLoadingStore();

  const [loadingNewConversation, setLoadingNewConversation] = useState(false);
  const [previousConversationCount, setPreviousConversationCount] = useState(0);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [conversationToDelete, setConversationToDelete] =
    useState<ChatConversation | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { selectedFilter, setSelectedFilter } = useKnowledgeFilter();

  // Delete session mutation
  const deleteSessionMutation = useDeleteSessionMutation({
    onSuccess: () => {
      toast.success("Conversation deleted successfully");

      // If we deleted the current conversation, select another one
      if (
        conversationToDelete &&
        currentConversationId === conversationToDelete.response_id
      ) {
        // Filter out the deleted conversation and find the next one
        const remainingConversations = conversations.filter(
          (conv) => conv.response_id !== conversationToDelete.response_id,
        );

        if (remainingConversations.length > 0) {
          // Load the first available conversation (most recent)
          loadConversation(remainingConversations[0]);
        } else {
          // No conversations left, start a new one
          setCurrentConversationId(null);
          if (onNewConversation) {
            onNewConversation();
          } else {
            refreshConversations();
            startNewConversation();
          }
        }
      }

      setDeleteModalOpen(false);
      setConversationToDelete(null);
    },
    onError: (error) => {
      toast.error(`Failed to delete conversation: ${error.message}`);
    },
  });

  const handleNewConversation = () => {
    setLoadingNewConversation(true);

    // Use the prop callback if provided, otherwise use the context method
    if (onNewConversation) {
      onNewConversation();
    } else {
      refreshConversations();
      startNewConversation();
    }

    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("newConversation"));
    }
    // Clear loading state after a short delay to show the new conversation is created
    setTimeout(() => {
      setLoadingNewConversation(false);
    }, 300);
  };

  const handleFileUpload = async (file: File) => {
    console.log("Navigation file upload:", file.name);

    // Trigger loading start event for chat page
    window.dispatchEvent(
      new CustomEvent("fileUploadStart", {
        detail: { filename: file.name },
      }),
    );

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("endpoint", endpoint);

      const response = await fetch("/api/upload_context", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorText = await response.text();
        console.error("Upload failed:", errorText);

        // Trigger error event for chat page to handle
        window.dispatchEvent(
          new CustomEvent("fileUploadError", {
            detail: {
              filename: file.name,
              error: "Failed to process document",
            },
          }),
        );

        // Trigger loading end event
        window.dispatchEvent(new CustomEvent("fileUploadComplete"));
        return;
      }

      const result = await response.json();
      console.log("Upload result:", result);

      // Add the file to conversation docs
      if (result.filename) {
        addConversationDoc(result.filename);
      }

      // Trigger file upload event for chat page to handle
      window.dispatchEvent(
        new CustomEvent("fileUploaded", {
          detail: { file, result },
        }),
      );

      // Trigger loading end event
      window.dispatchEvent(new CustomEvent("fileUploadComplete"));
    } catch (error) {
      console.error("Upload failed:", error);
      // Trigger loading end event even on error
      window.dispatchEvent(new CustomEvent("fileUploadComplete"));

      // Trigger error event for chat page to handle
      window.dispatchEvent(
        new CustomEvent("fileUploadError", {
          detail: { filename: file.name, error: "Failed to process document" },
        }),
      );
    }
  };

  const handleFilePickerClick = () => {
    fileInputRef.current?.click();
  };

  const handleFilePickerChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFileUpload(files[0]);
    }
    // Reset the input so the same file can be selected again
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleDeleteConversation = (
    conversation: ChatConversation,
    event?: React.MouseEvent,
  ) => {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    setConversationToDelete(conversation);
    setDeleteModalOpen(true);
  };

  const handleContextMenuAction = (
    action: string,
    conversation: ChatConversation,
  ) => {
    switch (action) {
      case "delete":
        handleDeleteConversation(conversation);
        break;
      // Add more actions here in the future (rename, duplicate, etc.)
      default:
        break;
    }
  };

  const confirmDeleteConversation = () => {
    if (conversationToDelete) {
      deleteSessionMutation.mutate({
        sessionId: conversationToDelete.response_id,
        endpoint: endpoint,
      });
    }
  };

  const routes = [
    {
      label: "Chat",
      icon: MessageSquare,
      href: "/chat",
      active: pathname === "/" || pathname.startsWith("/chat"),
    },
    {
      label: "Knowledge",
      icon: Library,
      href: "/knowledge",
      active: pathname.startsWith("/knowledge"),
    },
    {
      label: "Settings",
      icon: Settings2,
      href: "/settings",
      active: pathname.startsWith("/settings"),
    },
  ];

  const isOnChatPage = pathname === "/" || pathname === "/chat";
  const isOnKnowledgePage = pathname.startsWith("/knowledge");

  // Clear placeholder when conversation count increases (new conversation was created)
  useEffect(() => {
    const currentCount = conversations.length;

    // If we had a placeholder and the conversation count increased, clear the placeholder and highlight the new conversation
    if (
      placeholderConversation &&
      currentCount > previousConversationCount &&
      conversations.length > 0
    ) {
      setPlaceholderConversation(null);
      // Highlight the most recent conversation (first in sorted array) without loading its messages
      const newestConversation = conversations[0];
      if (newestConversation) {
        setCurrentConversationId(newestConversation.response_id);
      }
    }

    // Update the previous count
    setPreviousConversationCount(currentCount);
  }, [
    conversations.length,
    placeholderConversation,
    setPlaceholderConversation,
    previousConversationCount,
    conversations,
    setCurrentConversationId,
  ]);

  useEffect(() => {
    let activeConvo;

    if (currentConversationId && conversations.length > 0) {
      activeConvo = conversations.find(
        (conv) => conv.response_id === currentConversationId,
      );
    }

    if (isOnChatPage) {
      if (conversations.length === 0 && !placeholderConversation) {
        handleNewConversation();
      } else if (activeConvo && !conversationLoaded) {
        loadConversation(activeConvo);
        refreshConversations();
      } else if (
        conversations.length > 0 &&
        currentConversationId === null &&
        !placeholderConversation
      ) {
        handleNewConversation();
      }
    }
  }, [isOnChatPage, conversations, conversationLoaded]);

  const newConversationFiles = conversationData?.messages
    .filter(
      (message) =>
        message.role === "user" &&
        (message.content.match(FILES_REGEX)?.[0] ?? null) !== null,
    )
    .map((message) => message.content.match(FILES_REGEX)?.[0] ?? null)
    .concat(conversationDocs.map((doc) => doc.filename));

  return (
    <div className="flex flex-col h-full bg-background">
      <div className="px-4 py-2 flex-shrink-0">
        <div className="space-y-1">
          {routes.map((route) => (
            <div key={route.href}>
              <Link
                href={route.href}
                className={cn(
                  "text-[13px] group flex p-3 w-full justify-start font-medium cursor-pointer hover:bg-accent hover:text-accent-foreground rounded-lg transition-all",
                  route.active
                    ? "bg-accent text-accent-foreground shadow-sm"
                    : "text-foreground hover:text-accent-foreground",
                )}
              >
                <div className="flex items-center flex-1">
                  <route.icon
                    className={cn(
                      "h-[18px] w-[18px] mr-2 shrink-0",
                      route.active
                        ? "text-muted-foreground"
                        : "text-muted-foreground group-hover:text-muted-foreground",
                    )}
                  />
                  {route.label}
                </div>
              </Link>
              {route.label === "Settings" && (
                <div className="my-2 border-t border-border" />
              )}
            </div>
          ))}
        </div>
      </div>

      {isOnKnowledgePage && (
        <KnowledgeFilterList
          selectedFilter={selectedFilter}
          onFilterSelect={setSelectedFilter}
        />
      )}

      {/* Chat Page Specific Sections */}
      {isOnChatPage && (
        <div className="flex-1 min-h-0 flex flex-col px-4">
          {/* Conversations Section */}
          <div className="flex-shrink-0">
            <div className="flex items-center justify-between mb-3 mx-3">
              <h3 className="text-xs font-medium text-muted-foreground">
                Conversations
              </h3>
              <button
                type="button"
                className="p-1 hover:bg-accent rounded"
                onClick={handleNewConversation}
                title="Start new conversation"
                disabled={loading}
              >
                <Plus className="h-4 w-4 text-muted-foreground" />
              </button>
            </div>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto scrollbar-hide">
            <div className="space-y-1 flex flex-col">
              {loadingNewConversation || isConversationsLoading ? (
                <div className="text-[13px] text-muted-foreground p-2">
                  Loading...
                </div>
              ) : (
                <>
                  {/* Show placeholder conversation if it exists */}
                  {placeholderConversation && (
                    <button
                      type="button"
                      className="w-full px-3 rounded-lg bg-accent border border-dashed border-accent cursor-pointer group text-left h-[44px]"
                      onClick={() => {
                        // Don't load placeholder as a real conversation, just focus the input
                        if (typeof window !== "undefined") {
                          window.dispatchEvent(new CustomEvent("focusInput"));
                        }
                      }}
                    >
                      <div className="text-[13px] font-medium text-foreground truncate">
                        {placeholderConversation.title}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Start typing to begin...
                      </div>
                    </button>
                  )}

                  {/* Show regular conversations */}
                  {conversations.length === 0 && !placeholderConversation ? (
                    <div className="text-[13px] text-muted-foreground py-2 pl-3">
                      No conversations yet
                    </div>
                  ) : (
                    conversations.map((conversation) => (
                      <button
                        key={conversation.response_id}
                        type="button"
                        className={`w-full px-3 h-11 rounded-lg group relative text-left ${
                          loading
                            ? "opacity-50 cursor-not-allowed"
                            : "hover:bg-accent cursor-pointer"
                        } ${
                          currentConversationId === conversation.response_id
                            ? "bg-accent"
                            : ""
                        }`}
                        onClick={() => {
                          if (loading) return;
                          loadConversation(conversation);
                          refreshConversations();
                        }}
                        disabled={loading}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium text-foreground truncate">
                              {conversation.title}
                            </div>
                          </div>
                          <DropdownMenu>
                            <DropdownMenuTrigger
                              disabled={
                                loading || deleteSessionMutation.isPending
                              }
                              asChild
                            >
                              <div
                                className="opacity-0 group-hover:opacity-100 data-[state=open]:opacity-100 data-[state=open]:text-foreground transition-opacity p-1 hover:bg-accent rounded text-muted-foreground hover:text-foreground ml-2 flex-shrink-0 cursor-pointer"
                                title="More options"
                                role="button"
                                tabIndex={0}
                                onClick={(e) => {
                                  e.stopPropagation();
                                }}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter" || e.key === " ") {
                                    e.preventDefault();
                                    e.stopPropagation();
                                  }
                                }}
                              >
                                <EllipsisVertical className="h-4 w-4" />
                              </div>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                              side="bottom"
                              align="end"
                              className="w-48"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <DropdownMenuItem
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleContextMenuAction(
                                    "delete",
                                    conversation,
                                  );
                                }}
                                className="cursor-pointer text-destructive focus:text-destructive"
                              >
                                <Trash2 className="mr-2 h-4 w-4" />
                                Delete conversation
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                      </button>
                    ))
                  )}
                </>
              )}
            </div>

            {/* Conversation Knowledge Section - appears right after last conversation
            <div className="flex-shrink-0 mt-4">
              <div className="flex items-center justify-between mb-3 mx-3">
                <h3 className="text-xs font-medium text-muted-foreground">
                  Conversation knowledge
                </h3>
                <button
                  type="button"
                  onClick={handleFilePickerClick}
                  className="p-1 hover:bg-accent rounded"
                  disabled={loading}
                >
                  <Plus className="h-4 w-4 text-muted-foreground" />
                </button>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleFilePickerChange}
                className="hidden"
                accept=".pdf,.doc,.docx,.txt,.md,.rtf,.odt"
              />
              <div className="overflow-y-auto scrollbar-hide space-y-1">
                {conversationDocs.length === 0 ? (
                  <div className="text-[13px] text-muted-foreground py-2 px-3">
                    No documents yet
                  </div>
                ) : (
                  conversationDocs.map(doc => (
                    <div
                      key={`${doc.filename}-${doc.uploadTime.getTime()}`}
                      className="w-full px-3 h-11 rounded-lg hover:bg-accent cursor-pointer group flex items-center"
                    >
                      <FileText className="h-4 w-4 mr-2 text-muted-foreground flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-foreground truncate">
                          {doc.filename}
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div> */}
            <div className="flex-shrink-0 mt-4">
              <div className="flex items-center justify-between mb-3 mx-3">
                <h3 className="text-xs font-medium text-muted-foreground">
                  Files
                </h3>
              </div>
              <div className="overflow-y-auto scrollbar-hide space-y-1">
                {newConversationFiles?.length === 0 ? (
                  <div className="text-[13px] text-muted-foreground py-2 px-3">
                    No documents yet
                  </div>
                ) : (
                  newConversationFiles?.map((file, index) => (
                    <div
                      key={`${file}-${index}`}
                      className="flex-1 min-w-0 px-3"
                    >
                      <div className="text-mmd font-medium text-foreground truncate">
                        {file}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete Session Modal */}
      <DeleteSessionModal
        isOpen={deleteModalOpen}
        onClose={() => {
          setDeleteModalOpen(false);
          setConversationToDelete(null);
        }}
        onConfirm={confirmDeleteConversation}
        sessionTitle={conversationToDelete?.title || ""}
        isDeleting={deleteSessionMutation.isPending}
      />
    </div>
  );
}
