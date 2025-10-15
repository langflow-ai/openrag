"use client";

import { useState, useEffect } from "react";
import { Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import { useWidget } from "@/contexts/widget-context";

export default function WidgetsPage() {
  const { selectedWidget, setSelectedWidget, loadWidgets } = useWidget();
  const [prompt, setPrompt] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);

  // Load selected widget when changed
  useEffect(() => {
    if (selectedWidget) {
      loadWidgetPreview(selectedWidget);
    }
  }, [selectedWidget]);

  // Listen for focus input event
  useEffect(() => {
    const handleFocusInput = () => {
      const textarea = document.querySelector('textarea[placeholder*="Describe"]') as HTMLTextAreaElement;
      if (textarea) {
        textarea.focus();
      }
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
      <div className="border-t p-6 bg-background mt-6">
        <h2 className="text-sm font-medium mb-3">
          {selectedWidget ? "Create or Edit Widget" : "Create Widget"}
        </h2>
        <div className="space-y-3">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder={
              selectedWidget
                ? "Describe changes to make to the selected widget..."
                : "Describe the widget you want to build..."
            }
            className="w-full h-32 px-3 py-2 text-sm border rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-primary bg-background"
            disabled={isGenerating}
          />
          <div className="flex gap-2">
            {selectedWidget && (
              <button
                onClick={() => generateWidget(true)}
                disabled={isGenerating || !prompt.trim()}
                className="flex-1 py-2 px-4 bg-secondary text-secondary-foreground border rounded-lg hover:bg-secondary/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
              >
                {isGenerating ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Updating...
                  </>
                ) : (
                  <>
                    <Plus className="h-4 w-4" />
                    Update Selected
                  </>
                )}
              </button>
            )}
            <button
              onClick={() => generateWidget(false)}
              disabled={isGenerating || !prompt.trim()}
              className={`${selectedWidget ? 'flex-1' : 'w-full'} py-2 px-4 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2`}
            >
              {isGenerating ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Plus className="h-4 w-4" />
                  Create New
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
