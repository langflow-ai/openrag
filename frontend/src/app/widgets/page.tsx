"use client";

import { Suspense, useState, useEffect, useRef } from "react";
import { Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import TextareaAutosize from "react-textarea-autosize";
import { useWidget } from "@/contexts/widget-context";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ProtectedRoute } from "@/components/protected-route";

interface Connector {
  id: string;
  name: string;
  description: string;
  icon: string;
  available: boolean;
}

function WidgetsPage() {
  const { selectedWidget, setSelectedWidget, loadWidgets } = useWidget();
  const [prompt, setPrompt] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [isConnectorPopoverOpen, setIsConnectorPopoverOpen] = useState(false);
  const [textareaHeight, setTextareaHeight] = useState(40);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Load selected widget when changed
  useEffect(() => {
    if (selectedWidget) {
      loadWidgetPreview(selectedWidget);
    }
  }, [selectedWidget]);

  // Load connectors on mount
  useEffect(() => {
    const loadConnectors = async () => {
      try {
        const response = await fetch("/api/connectors");
        if (response.ok) {
          const data = await response.json();
          const connectorsList = Object.entries(data.connectors).map(([id, info]: [string, any]) => ({
            id,
            name: info.name,
            description: info.description,
            icon: info.icon,
            available: info.available,
          }));
          setConnectors(connectorsList.filter(c => c.available));
        }
      } catch (error) {
        console.error("Failed to load connectors:", error);
      }
    };
    loadConnectors();
  }, []);

  // Auto-focus the input on component mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Listen for focus input event (when new widget button is clicked)
  useEffect(() => {
    const handleFocusInput = () => {
      inputRef.current?.focus();
    };

    window.addEventListener("focusWidgetInput", handleFocusInput);
    return () => window.removeEventListener("focusWidgetInput", handleFocusInput);
  }, []);

  const loadWidgetPreview = async (widgetId: string) => {
    try {
      const iframe = document.getElementById(`widget-iframe-${widgetId}`) as HTMLIFrameElement;
      if (!iframe) return;

      const timestamp = Date.now();

      // Create HTML content for iframe
      const iframeContent = `
        <!DOCTYPE html>
        <html>
          <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
              body {
                margin: 0;
                padding: 0;
                font-family: system-ui, -apple-system, sans-serif;
              }
            </style>
            <link rel="stylesheet" href="/widgets/assets/${widgetId}.css?t=${timestamp}" onerror="this.remove()">
          </head>
          <body>
            <div id="root"></div>
            <script type="module" src="/widgets/assets/${widgetId}.js?t=${timestamp}"></script>
          </body>
        </html>
      `;

      // Write content to iframe
      iframe.srcdoc = iframeContent;

    } catch (error) {
      console.error("Failed to load widget preview:", error);
      toast.error("Failed to load widget preview");
    }
  };

  const generateWidget = async (isIteration = false) => {
    if (!prompt.trim()) {
      toast.error("Please enter a prompt");
      return;
    }

    // If iterating, require a selected widget
    if (isIteration && !selectedWidget) {
      toast.error("Please select a widget to iterate on");
      return;
    }

    try {
      setIsGenerating(true);
      const response = await fetch("/api/widgets/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          base_widget_id: isIteration ? selectedWidget : undefined
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || "Failed to generate widget");
      }

      const data = await response.json();
      toast.success(isIteration ? "Widget updated successfully!" : "Widget generated successfully!");

      // Reload widgets list
      await loadWidgets();

      // Select the new widget
      setSelectedWidget(data.widget_id);

      // Clear prompt
      setPrompt("");
    } catch (error: any) {
      console.error("Failed to generate widget:", error);
      toast.error(error.message || "Failed to generate widget");
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* Preview Area */}
      <div className="flex-1 overflow-auto flex flex-col items-center py-6">
        <div className="w-[768px] h-[404px] rounded-lg bg-background overflow-hidden shadow-sm">
          {selectedWidget ? (
            <iframe
              id={`widget-iframe-${selectedWidget}`}
              className="w-full h-full border-0"
              sandbox="allow-scripts allow-same-origin allow-forms"
              title="Widget Preview"
            />
          ) : (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              Select a widget to preview
            </div>
          )}
        </div>
      </div>

      {/* Chat Input Area */}
      <div className="pb-8 pt-4 flex px-6">
        <div className="w-full">
          <form onSubmit={(e) => { e.preventDefault(); generateWidget(!!selectedWidget); }} className="relative">
            <div className="relative w-full bg-muted/20 rounded-lg border border-border/50 focus-within:ring-1 focus-within:ring-ring">
              <div className="relative" style={{ height: `${textareaHeight + 60}px` }}>
                <TextareaAutosize
                  ref={inputRef}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  onHeightChange={(height) => setTextareaHeight(height)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      if (prompt.trim() && !isGenerating) {
                        generateWidget(!!selectedWidget);
                      }
                    }
                  }}
                  maxRows={7}
                  minRows={2}
                  placeholder={
                    selectedWidget
                      ? "Describe changes to make to the selected widget..."
                      : "Describe the widget you want to build..."
                  }
                  disabled={isGenerating}
                  className="w-full bg-transparent px-4 pt-4 focus-visible:outline-none resize-none"
                  rows={2}
                />
                <div
                  className="absolute bottom-0 left-0 right-0 bg-transparent pointer-events-none"
                  style={{ height: "60px" }}
                />
              </div>
            </div>

            <Popover open={isConnectorPopoverOpen} onOpenChange={setIsConnectorPopoverOpen}>
              <PopoverTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  size="iconSm"
                  className="absolute bottom-3 left-3 h-8 w-8 p-0 rounded-full hover:bg-muted/50"
                  disabled={isGenerating}
                >
                  <Plus className="h-4 w-4" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-48 p-2" side="top" align="start" sideOffset={6}>
                <div className="space-y-1">
                  {connectors.length === 0 ? (
                    <div className="px-2 py-3 text-sm text-muted-foreground">
                      No connectors available
                    </div>
                  ) : (
                    connectors.map((connector) => (
                      <button
                        key={connector.id}
                        type="button"
                        onClick={() => {
                          // Placeholder - doesn't do anything yet
                          setIsConnectorPopoverOpen(false);
                        }}
                        className="w-full overflow-hidden text-left px-2 py-2 gap-2 text-sm rounded hover:bg-muted/50 flex items-center justify-between"
                      >
                        <div className="overflow-hidden">
                          <div className="font-medium truncate">
                            {connector.name}
                          </div>
                        </div>
                      </button>
                    ))
                  )}
                </div>
              </PopoverContent>
            </Popover>

            <Button
              type="submit"
              disabled={!prompt.trim() || isGenerating}
              className="absolute bottom-3 right-3 rounded-lg h-10 px-4"
            >
              {isGenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : "Send"}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default function ProtectedWidgetsPage() {
  return (
    <ProtectedRoute>
      <Suspense fallback={<div>Loading widgets...</div>}>
        <WidgetsPage />
      </Suspense>
    </ProtectedRoute>
  );
}
