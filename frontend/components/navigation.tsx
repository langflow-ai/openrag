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
    refreshConversations,
    placeholderConversation,
    setPlaceholderConversation,
    conversationLoaded,
  } = useChat();

  const { loading } = useLoadingStore();

  useEffect(() => {
    console.log("loading", loading);
  }, [loading]);

  const [previousConversationCount, setPreviousConversationCount] = useState(0);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [conversationToDelete, setConversationToDelete] =
    useState<ChatConversation | null>(null);
  const hasCompletedInitialLoad = useRef(false);
  const mountTimeRef = useRef<number | null>(null);

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

  // Track mount time to prevent auto-selection right after component mounts (e.g., after onboarding)
  useEffect(() => {
    if (mountTimeRef.current === null) {
      mountTimeRef.current = Date.now();
    }
  }, []);

  // Track when initial load completes
  useEffect(() => {
    if (!isConversationsLoading && !hasCompletedInitialLoad.current) {
      hasCompletedInitialLoad.current = true;
      // Set initial count after first load completes
      setPreviousConversationCount(conversations.length);
    }
  }, [isConversationsLoading, conversations.length]);

  // Clear placeholder when conversation count increases (new conversation was created)
  useEffect(() => {
    const currentCount = conversations.length;
    const timeSinceMount = mountTimeRef.current
      ? Date.now() - mountTimeRef.current
      : Infinity;
    const MIN_TIME_AFTER_MOUNT = 2000; // 2 seconds - prevents selection right after onboarding

    // Only select if:
    // 1. We have a placeholder (new conversation was created)
    // 2. Initial load has completed (prevents selection on browser refresh)
    // 3. Count increased (new conversation appeared)
    // 4. Not currently loading
    // 5. Enough time has passed since mount (prevents selection after onboarding completes)
    if (
      placeholderConversation &&
      hasCompletedInitialLoad.current &&
      currentCount > previousConversationCount &&
      conversations.length > 0 &&
      !isConversationsLoading &&
      timeSinceMount >= MIN_TIME_AFTER_MOUNT
    ) {
      setPlaceholderConversation(null);
      // Highlight the most recent conversation (first in sorted array) without loading its messages
      const newestConversation = conversations[0];
      if (newestConversation) {
        setCurrentConversationId(newestConversation.response_id);
      }
    }

    // Update the previous count only after initial load
    if (hasCompletedInitialLoad.current) {
      setPreviousConversationCount(currentCount);
    }
  }, [
    conversations.length,
    placeholderConversation,
    setPlaceholderConversation,
    previousConversationCount,
    conversations,
    setCurrentConversationId,
    isConversationsLoading,
  ]);

  useEffect(() => {
    let activeConvo;

    if (currentConversationId && conversations.length > 0) {
      activeConvo = conversations.find(
        (conv) => conv.response_id === currentConversationId,
      );
    }

    if (isOnChatPage && !isConversationsLoading) {
      if (conversations.length === 0 && !placeholderConversation) {
        handleNewConversation();
      } else if (activeConvo) {
        loadConversation(activeConvo);
        // Don't call refreshConversations here - it causes unnecessary refetches
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
              {/* Show skeleton loaders when loading and no conversations exist */}
              {isConversationsLoading && conversations.length === 0 ? (
                [0, 1].map((skeletonIndex) => (
                  <div
                    key={`conversation-skeleton-${skeletonIndex}`}
                    className={cn(
                      "w-full px-3 h-11 rounded-lg animate-pulse",
                      skeletonIndex === 0 ? "bg-accent/50" : "",
                    )}
                  >
                    <div className="h-3 bg-muted-foreground/20 rounded w-3/4 mt-3.5" />
                  </div>
                ))
              ) : (
                <>
                  {/* Show regular conversations */}
                  {conversations.length === 0 && !isConversationsLoading ? (
                    <div className="text-[13px] text-muted-foreground py-2 pl-3">
                      No conversations yet
                    </div>
                  ) : (
                    <>
                      {/* Optimistic rendering: Show placeholder conversation button while loading */}
                      {(() => {
                        // Show placeholder when:
                        // 1. Loading is true AND conversation doesn't exist yet (creating new conversation), OR
                        // 2. currentConversationId exists but isn't in conversations yet (gap between response and list update)
                        const conversationExists = currentConversationId
                          ? conversations.some(
                              (conv) => conv.response_id === currentConversationId,
                            )
                          : false;

                        const shouldShowPlaceholder =
                          !conversationExists &&
                          (loading ||
                            (currentConversationId !== null &&
                              currentConversationId !== undefined));

                        // Use placeholderConversation if available
                        // Otherwise create a placeholder with currentConversationId if it exists
                        // Or use a temporary ID if we're loading but don't have an ID yet
                        const placeholderToShow =
                          placeholderConversation
                            ? placeholderConversation
                            : currentConversationId
                              ? {
                                  response_id: currentConversationId,
                                  title: "",
                                  endpoint: endpoint,
                                  messages: [],
                                  total_messages: 0,
                                }
                              : loading
                                ? {
                                    response_id: `loading-${Date.now()}`,
                                    title: "",
                                    endpoint: endpoint,
                                    messages: [],
                                    total_messages: 0,
                                  }
                                : null;

                        return (
                          shouldShowPlaceholder &&
                          placeholderToShow && (
                            <button
                              key={placeholderToShow.response_id}
                              type="button"
                              className="w-full px-3 h-11 rounded-lg bg-accent group relative text-left cursor-not-allowed"
                              disabled
                            >
                              <div className="flex items-center justify-between">
                                <div className="flex-1 min-w-0">
                                  <div className="text-sm font-medium text-muted-foreground truncate">
                                    <span className="thinking-dots"></span>
                                  </div>
                                </div>
                              </div>
                            </button>
                          )
                        );
                      })()}
                      {conversations.map((conversation) => (
                        <button
                        key={conversation.response_id}
                        type="button"
                        className={`w-full px-3 h-11 rounded-lg group relative text-left ${
                          loading || isConversationsLoading
                            ? "opacity-50 cursor-not-allowed"
                            : "hover:bg-accent cursor-pointer"
                        } ${
                          currentConversationId === conversation.response_id
                            ? "bg-accent"
                            : ""
                        }`}
                        onClick={() => {
                          if (loading || isConversationsLoading) return;
                          loadConversation(conversation);
                          // Don't refresh - just loading an existing conversation
                        }}
                        disabled={loading || isConversationsLoading}
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
                                loading ||
                                isConversationsLoading ||
                                deleteSessionMutation.isPending
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
                    ))}
                    </>
                  )}
                </>
              )}
            </div>
            {(newConversationFiles?.length ?? 0) !== 0 && (
              <div className="flex-shrink-0 mt-4">
                <div className="flex items-center justify-between mb-3 mx-3">
                  <h3 className="text-xs font-medium text-muted-foreground">
                    Files
                  </h3>
                </div>
                <div className="overflow-y-auto scrollbar-hide space-y-1">
                  {newConversationFiles?.map((file, index) => (
                    <div
                      key={`${file}-${index}`}
                      className="flex-1 min-w-0 px-3"
                    >
                      <div className="text-mmd font-medium text-foreground truncate">
                        {file}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
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
