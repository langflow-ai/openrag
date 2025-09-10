"use client";

import { useChat } from "@/contexts/chat-context";
import { cn } from "@/lib/utils";
import {
  FileText,
  Library,
  MessageSquare,
  Plus,
  Settings2,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { EndpointType } from "@/contexts/chat-context";
import { useLoadingStore } from "@/stores/loadingStore";

interface RawConversation {
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

interface ChatConversation {
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

export function Navigation() {
  const pathname = usePathname();
  const {
    endpoint,
    refreshTrigger,
    loadConversation,
    currentConversationId,
    setCurrentConversationId,
    startNewConversation,
    conversationDocs,
    addConversationDoc,
    refreshConversations,
    placeholderConversation,
    setPlaceholderConversation,
  } = useChat();

  const { loading } = useLoadingStore();

  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [loadingNewConversation, setLoadingNewConversation] = useState(false);
  const [previousConversationCount, setPreviousConversationCount] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleNewConversation = () => {
    setLoadingNewConversation(true);
    refreshConversations();
    startNewConversation();
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
      })
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
          })
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
        })
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
        })
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

  const routes = [
    {
      label: "Chat",
      icon: MessageSquare,
      href: "/chat",
      active: pathname === "/" || pathname === "/chat",
    },
    {
      label: "Knowledge",
      icon: Library,
      href: "/knowledge",
      active: pathname === "/knowledge",
    },
    {
      label: "Settings",
      icon: Settings2,
      href: "/settings",
      active: pathname === "/settings",
    },
  ];

  const isOnChatPage = pathname === "/" || pathname === "/chat";

  const createDefaultPlaceholder = useCallback(() => {
    return {
      response_id: "new-conversation-" + Date.now(),
      title: "New conversation",
      endpoint: endpoint,
      messages: [
        {
          role: "assistant",
          content: "How can I assist?",
          timestamp: new Date().toISOString(),
        },
      ],
      created_at: new Date().toISOString(),
      last_activity: new Date().toISOString(),
      total_messages: 1,
    } as ChatConversation;
  }, [endpoint]);

  const fetchConversations = useCallback(async () => {
    setLoadingConversations(true);
    try {
      // Fetch from the selected endpoint only
      const apiEndpoint =
        endpoint === "chat" ? "/api/chat/history" : "/api/langflow/history";

      const response = await fetch(apiEndpoint);
      if (response.ok) {
        const history = await response.json();
        const rawConversations = history.conversations || [];

        // Cast conversations to proper type and ensure endpoint is correct
        const conversations: ChatConversation[] = rawConversations.map(
          (conv: RawConversation) => ({
            ...conv,
            endpoint: conv.endpoint as EndpointType,
          })
        );

        // Sort conversations by last activity (most recent first)
        conversations.sort((a: ChatConversation, b: ChatConversation) => {
          const aTime = new Date(
            a.last_activity || a.created_at || 0
          ).getTime();
          const bTime = new Date(
            b.last_activity || b.created_at || 0
          ).getTime();
          return bTime - aTime;
        });

        setConversations(conversations);

        // If no conversations exist and no placeholder is shown, create a default placeholder
        if (conversations.length === 0 && !placeholderConversation) {
          setPlaceholderConversation(createDefaultPlaceholder());
        }
      } else {
        setConversations([]);

        // Also create placeholder when request fails and no conversations exist
        if (!placeholderConversation) {
          setPlaceholderConversation(createDefaultPlaceholder());
        }
      }

      // Conversation documents are now managed in chat context
    } catch (error) {
      console.error(`Failed to fetch ${endpoint} conversations:`, error);
      setConversations([]);
    } finally {
      setLoadingConversations(false);
    }
  }, [
    endpoint,
    placeholderConversation,
    setPlaceholderConversation,
    createDefaultPlaceholder,
  ]);

  // Fetch chat conversations when on chat page, endpoint changes, or refresh is triggered
  useEffect(() => {
    if (isOnChatPage) {
      fetchConversations();
    }
  }, [isOnChatPage, endpoint, refreshTrigger, fetchConversations]);

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

  return (
    <div className="space-y-4 py-4 flex flex-col h-full bg-background">
      <div className="px-3 py-2 flex-shrink-0">
        <div className="space-y-1">
          {routes.map((route) => (
            <div key={route.href}>
              <Link
                href={route.href}
                className={cn(
                  "text-sm group flex p-3 w-full justify-start font-medium cursor-pointer hover:bg-accent hover:text-accent-foreground rounded-lg transition-all",
                  route.active
                    ? "bg-accent text-accent-foreground shadow-sm"
                    : "text-foreground hover:text-accent-foreground"
                )}
              >
                <div className="flex items-center flex-1">
                  <route.icon
                    className={cn(
                      "h-4 w-4 mr-3 shrink-0",
                      route.active
                        ? "text-accent-foreground"
                        : "text-muted-foreground group-hover:text-foreground"
                    )}
                  />
                  {route.label}
                </div>
              </Link>
              {route.label === "Settings" && (
                <div className="mx-3 my-2 border-t border-border/40" />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Chat Page Specific Sections */}
      {isOnChatPage && (
        <div className="flex-1 min-h-0 flex flex-col">
          {/* Conversations Section */}
          <div className="px-3 flex-shrink-0">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-muted-foreground">
                Conversations
              </h3>
              <button
                className="p-1 hover:bg-accent rounded"
                onClick={handleNewConversation}
                title="Start new conversation"
                disabled={loading}
              >
                <Plus className="h-4 w-4 text-muted-foreground" />
              </button>
            </div>
          </div>

          <div className="px-3 flex-1 min-h-0 flex flex-col">
            {/* Conversations List - grows naturally, doesn't fill all space */}
            <div className="flex-shrink-0 overflow-y-auto scrollbar-hide space-y-1 max-h-full">
              {loadingNewConversation ? (
                <div className="text-sm text-muted-foreground p-2">
                  Loading...
                </div>
              ) : (
                <>
                  {/* Show placeholder conversation if it exists */}
                  {placeholderConversation && (
                    <div
                      className="p-2 rounded-lg bg-accent/50 border border-dashed border-accent cursor-pointer group"
                      onClick={() => {
                        // Don't load placeholder as a real conversation, just focus the input
                        if (typeof window !== "undefined") {
                          window.dispatchEvent(new CustomEvent("focusInput"));
                        }
                      }}
                    >
                      <div className="text-sm font-medium text-foreground mb-1 truncate">
                        {placeholderConversation.title}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Start typing to begin...
                      </div>
                    </div>
                  )}

                  {/* Show regular conversations */}
                  {conversations.length === 0 && !placeholderConversation ? (
                    <div className="text-sm text-muted-foreground p-2">
                      No conversations yet
                    </div>
                  ) : (
                    conversations.map((conversation) => (
                      <div
                        key={conversation.response_id}
                        className={`p-2 rounded-lg group ${
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
                      >
                        <div className="text-sm font-medium text-foreground mb-1 truncate">
                          {conversation.title}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {conversation.total_messages} messages
                        </div>
                        {conversation.last_activity && (
                          <div className="text-xs text-muted-foreground">
                            {new Date(
                              conversation.last_activity
                            ).toLocaleDateString()}
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </>
              )}
            </div>

            {/* Conversation Knowledge Section - appears right after last conversation */}
            <div className="flex-shrink-0 mt-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-muted-foreground">
                  Conversation knowledge
                </h3>
                <button
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
              <div className="overflow-y-auto scrollbar-hide space-y-1 max-h-40">
                {conversationDocs.length === 0 ? (
                  <div className="text-sm text-muted-foreground p-2">
                    No documents yet
                  </div>
                ) : (
                  conversationDocs.map((doc, index) => (
                    <div
                      key={index}
                      className="p-2 rounded-lg hover:bg-accent cursor-pointer group flex items-center"
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
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
