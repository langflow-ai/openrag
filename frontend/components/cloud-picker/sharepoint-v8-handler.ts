"use client";

import { CloudFile } from "./types";

/**
 * SharePoint File Picker v8 Handler
 * 
 * Uses Microsoft's newer File Picker v8 which communicates via postMessage
 * instead of the deprecated OneDrive.js SDK (v7.2) that has bugs with SharePoint.
 * 
 * Reference: https://learn.microsoft.com/en-us/onedrive/developer/controls/file-pickers/
 */

interface PickerOptions {
  sdk: string;
  entry: {
    oneDrive?: {
      files?: { folder?: string };
    };
    sharePoint?: {
      byPath?: {
        web?: string;
        list?: string;
        folder?: string;
      };
    };
  };
  authentication: Record<string, unknown>;
  messaging: {
    origin: string;
    channelId: string;
  };
  selection?: {
    mode?: "single" | "multiple";
  };
  typesAndSources?: {
    mode?: "files" | "folders" | "all";
  };
  commands?: {
    pick?: {
      action?: "select" | "share" | "download";
      select?: {
        urls?: {
          download?: boolean;
        };
      };
    };
  };
}

interface PickedItem {
  id: string;
  name: string;
  size?: number;
  file?: {
    mimeType?: string;
  };
  folder?: Record<string, unknown>;
  webUrl?: string;
  lastModifiedDateTime?: string;
  "@microsoft.graph.downloadUrl"?: string;
  parentReference?: {
    driveId: string;
  };
  "@sharePoint.endpoint"?: string;
}

interface PickCommand {
  command: "pick";
  items: PickedItem[];
}

interface AuthenticateCommand {
  command: "authenticate";
  resource: string;
  type: string;
}

interface CloseCommand {
  command: "close";
}

type PickerCommand = PickCommand | AuthenticateCommand | CloseCommand | { command: string };

function tryParseUrl(value?: string | null): URL | null {
  if (!value) return null;
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

function isGraphHostname(hostname: string | null | undefined): boolean {
  return hostname?.toLowerCase() === "graph.microsoft.com";
}

function isSharePointHostname(hostname: string | null | undefined): boolean {
  if (!hostname) return false;
  const h = hostname.toLowerCase();
  return h === "sharepoint.com" || h.endsWith(".sharepoint.com");
}

function hostnamesMatch(a: URL | null, b: URL | null): boolean {
  if (!a || !b) return false;
  return a.hostname.toLowerCase() === b.hostname.toLowerCase();
  // Optionally also check protocol: a.protocol === b.protocol
}

export class SharePointV8Handler {
  private win: Window | null = null;
  private port: MessagePort | null = null;
  private channelId: string;
  private baseUrl: string;
  private accessToken: string;
  private clientId: string;
  private onFileSelected: ((files: CloudFile[]) => void) | null = null;
  private onPickerStateChange: ((isOpen: boolean) => void) | null = null;
  private messageListener: ((event: MessageEvent) => void) | null = null;

  constructor(
    baseUrl: string,
    accessToken: string,
    clientId: string,
    onPickerStateChange?: (isOpen: boolean) => void
  ) {
    this.baseUrl = baseUrl;
    this.accessToken = accessToken;
    this.clientId = clientId;
    this.channelId = this.generateUUID();
    this.onPickerStateChange = onPickerStateChange || null;
  }

  private generateUUID(): string {
    // Generate a UUID v4
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  async loadPickerApi(): Promise<boolean> {
    // v8 picker doesn't require loading an SDK - it's all postMessage based
    // We just need to verify we have the required parameters
    return !!(this.baseUrl && this.accessToken && this.clientId);
  }

  openPicker(onFileSelected: (files: CloudFile[]) => void): void {
    this.onFileSelected = onFileSelected;
    this.onPickerStateChange?.(true);

    // === DIAGNOSTIC LOGGING START ===
    console.log("=== SharePoint v8 Picker Diagnostics ===");
    console.log("Base URL:", this.baseUrl);
    console.log("Client ID:", this.clientId);
    console.log("Token (first 20 chars):", this.accessToken?.substring(0, 20) + "...");
    console.log("Token length:", this.accessToken?.length);
    console.log("Window origin:", window.location.origin);
    // === DIAGNOSTIC LOGGING END ===

    try {
      // Generate a new channel ID for this picker instance
      this.channelId = this.generateUUID();

      // Open popup window (recommended size by Microsoft: 1080x680, min: 250x230)
      this.win = window.open("", "SharePointPicker", "width=1080,height=680");

      if (!this.win) {
        console.error("Failed to open picker popup - popup may be blocked");
        this.onPickerStateChange?.(false);
        return;
      }

      // Create picker configuration
      const options: PickerOptions = {
        sdk: "8.0",
        entry: {
          // For SharePoint, we use oneDrive entry which accesses the user's OneDrive
          // This works for both personal OneDrive and OneDrive for Business/SharePoint
          oneDrive: {
            files: {},
          },
        },
        // Empty authentication object tells picker we'll provide tokens via messaging
        authentication: {},
        messaging: {
          origin: window.location.origin,
          channelId: this.channelId,
        },
        selection: {
          mode: "multiple",
        },
        typesAndSources: {
          mode: "all", // Allow both files and folders
        },
        commands: {
          pick: {
            action: "select",
            select: {
              urls: {
                download: true, // Request download URLs
              },
            },
          },
        },
      };

      // Build the URL with configuration in query string
      const queryString = new URLSearchParams({
        filePicker: JSON.stringify(options),
        locale: "en-us",
      });

      const pickerUrl = `${this.baseUrl}/_layouts/15/FilePicker.aspx?${queryString}`;
      
      // === DIAGNOSTIC: Log picker URL and options ===
      console.log("Picker URL (full):", pickerUrl);
      console.log("Picker options:", JSON.stringify(options, null, 2));
      console.log("Channel ID:", this.channelId);

      // OPTION A FIX: Don't POST the token via form - let picker request it via authenticate command
      // The form-posted token might be causing "invalid_client" errors
      // Reference: https://learn.microsoft.com/en-us/onedrive/developer/controls/file-pickers/
      
      // === DIAGNOSTIC: Token delivery method ===
      console.log("Token delivery method: authenticate command only (no form POST)");
      console.log("Token will be provided when picker sends 'authenticate' command");
      
      // Use GET request instead of POST with token
      // Simply navigate to the picker URL - token will be provided via messaging
      this.win.location.href = pickerUrl;

      // Setup message listener for communication with picker
      this.messageListener = this.handleWindowMessage.bind(this);
      window.addEventListener("message", this.messageListener);

      // Monitor if popup is closed by user
      const checkClosed = setInterval(() => {
        if (this.win?.closed) {
          clearInterval(checkClosed);
          this.cleanup();
        }
      }, 500);
    } catch (error) {
      console.error("Error opening SharePoint v8 picker:", error);
      this.cleanup();
    }
  }

  private handleWindowMessage(event: MessageEvent): void {
    // === DIAGNOSTIC: Log all messages from picker window (before filtering) ===
    if (event.source === this.win) {
      console.log("SharePoint v8 picker: Window message received:", event.data?.type || "unknown");
    }
    
    // Verify the message is from our picker window
    if (event.source !== this.win) {
      return;
    }

    const message = event.data;
    
    // === DIAGNOSTIC: Log full message data ===
    console.log("SharePoint v8 picker: Message data:", JSON.stringify(message, null, 2));

    // Handle initialization message
    if (message.type === "initialize" && message.channelId === this.channelId) {
      console.log("SharePoint v8 picker: Received initialize message");
      console.log("SharePoint v8 picker: Channel ID match:", message.channelId === this.channelId);

      // Get the MessagePort for further communication
      this.port = event.ports[0];
      console.log("SharePoint v8 picker: Port received:", !!this.port);

      if (this.port) {
        // Setup port message handler
        this.port.addEventListener("message", this.handlePortMessage.bind(this));
        this.port.start();

        // Activate the picker
        this.port.postMessage({ type: "activate" });
        console.log("SharePoint v8 picker: Activated, sent activate message");
      } else {
        console.error("SharePoint v8 picker: No MessagePort received in initialize message!");
      }
    } else if (message.type === "error") {
      // === DIAGNOSTIC: Handle error messages from picker ===
      console.error("SharePoint v8 picker: Error message from picker window:", message);
    } else if (message.channelId && message.channelId !== this.channelId) {
      console.warn("SharePoint v8 picker: Channel ID mismatch! Expected:", this.channelId, "Got:", message.channelId);
    }
  }

  private handlePortMessage(event: MessageEvent): void {
    const payload = event.data;
    console.log("SharePoint v8 picker: Port message received:", payload.type);
    // === DIAGNOSTIC: Log full payload for debugging ===
    console.log("SharePoint v8 picker: Full payload:", JSON.stringify(payload, null, 2));

    switch (payload.type) {
      case "notification":
        this.handleNotification(payload.data);
        break;

      case "command":
        this.handleCommand(payload.id, payload.data);
        break;
        
      case "error":
        // === DIAGNOSTIC: Log any error type messages ===
        console.error("SharePoint v8 picker: Error message received:", payload);
        break;
        
      default:
        console.log("SharePoint v8 picker: Unknown payload type:", payload.type);
    }
  }

  private handleNotification(notification: { notification: string }): void {
    console.log("SharePoint v8 picker: Notification:", notification.notification);

    if (notification.notification === "page-loaded") {
      console.log("SharePoint v8 picker: Page loaded and ready");
    }
  }

  private handleCommand(id: string, command: PickerCommand): void {
    // All commands must be acknowledged first
    this.port?.postMessage({
      type: "acknowledge",
      id: id,
    });

    console.log("SharePoint v8 picker: Command:", command.command);

    switch (command.command) {
      case "authenticate":
        this.handleAuthenticate(id, command as AuthenticateCommand);
        break;

      case "pick":
        this.handlePick(id, command as PickCommand);
        break;

      case "close":
        this.handleClose(id);
        break;

      default:
        // Unknown command - send error response
        this.port?.postMessage({
          type: "result",
          id: id,
          data: {
            result: "error",
            error: {
              code: "unsupportedCommand",
              message: `Command not supported: ${command.command}`,
            },
          },
        });
    }
  }

  private handleAuthenticate(id: string, command: AuthenticateCommand): void {
    // === DIAGNOSTIC: Full auth command details ===
    console.log("=== SharePoint v8 Picker Auth Request ===");
    console.log("Auth request ID:", id);
    console.log("Auth request resource:", command.resource);
    console.log("Auth request type:", command.type);
    console.log("Full auth command:", JSON.stringify(command, null, 2));
    
    // Check if resource matches our base URL or is Microsoft Graph using URL parsing
    const resourceUrl = tryParseUrl(command.resource);
    const baseUrl = tryParseUrl(this.baseUrl);

    const isGraphResource = resourceUrl ? isGraphHostname(resourceUrl.hostname) : false;
    const isSharePointResource = resourceUrl ? isSharePointHostname(resourceUrl.hostname) : false;
    const resourceMatchesBase = hostnamesMatch(resourceUrl, baseUrl);

    console.log("Resource analysis:");
    console.log("  - Is Microsoft Graph resource:", isGraphResource);
    console.log("  - Is SharePoint resource:", isSharePointResource);
    console.log("  - Resource matches our baseUrl:", resourceMatchesBase);
    console.log("  - Our baseUrl:", this.baseUrl);
    
    // IMPORTANT: Our token is for Microsoft Graph API (audience: https://graph.microsoft.com)
    // If the picker requests a SharePoint-specific resource, the token might not work
    console.log("Token audience: https://graph.microsoft.com (Microsoft Graph)");
    
    if (isSharePointResource && !isGraphResource) {
      console.warn("⚠️ POTENTIAL ISSUE: Picker requested SharePoint resource, but our token is for Microsoft Graph!");
      console.warn("⚠️ This mismatch could cause 'invalid_client' errors.");
      console.warn("⚠️ The token audience might need to be the SharePoint domain instead.");
    }
    
    // Log token details (safely)
    console.log("Token to provide (first 30 chars):", this.accessToken?.substring(0, 30) + "...");
    console.log("Token to provide (length):", this.accessToken?.length);
    
    // Decode JWT header to show audience (if present)
    try {
      const tokenParts = this.accessToken?.split(".");
      if (tokenParts && tokenParts.length >= 2) {
        const payload = JSON.parse(atob(tokenParts[1]));
        console.log("Token claims (decoded):");
        console.log("  - aud (audience):", payload.aud);
        console.log("  - iss (issuer):", payload.iss);
        console.log("  - scp (scopes):", payload.scp);
        console.log("  - exp (expiry):", new Date(payload.exp * 1000).toISOString());
      }
    } catch (e) {
      console.log("Could not decode token (may not be JWT):", e);
    }

    // For now, we use the same token for all requests
    // In a production app, you might need to acquire different tokens for different resources
    try {
      this.port?.postMessage({
        type: "result",
        id: id,
        data: {
          result: "token",
          token: this.accessToken,
        },
      });
      console.log("SharePoint v8 picker: Successfully sent auth token response");
    } catch (error) {
      console.error("SharePoint v8 picker: Failed to provide auth token:", error);
      this.port?.postMessage({
        type: "result",
        id: id,
        data: {
          result: "error",
          error: {
            code: "unableToObtainToken",
            message: error instanceof Error ? error.message : "Failed to obtain token",
          },
        },
      });
    }
  }

  private handlePick(id: string, command: PickCommand): void {
    console.log("SharePoint v8 picker: Files picked:", command.items?.length);

    try {
      // Convert picked items to CloudFile format
      const files: CloudFile[] = (command.items || []).map((item) => {
        // Determine mime type
        let mimeType = item.file?.mimeType;
        if (!mimeType && item.name) {
          mimeType = this.inferMimeType(item.name);
        }

        return {
          id: item.id,
          name: item.name || "Unknown",
          mimeType: mimeType || "application/octet-stream",
          webUrl: item.webUrl || "",
          downloadUrl: item["@microsoft.graph.downloadUrl"] || "",
          size: item.size,
          modifiedTime: item.lastModifiedDateTime,
          isFolder: !!item.folder,
        };
      });

      // Call the callback with selected files
      if (this.onFileSelected) {
        this.onFileSelected(files);
      }

      // Send success response
      this.port?.postMessage({
        type: "result",
        id: id,
        data: {
          result: "success",
        },
      });

      // Close the picker
      this.win?.close();
      this.cleanup();
    } catch (error) {
      console.error("SharePoint v8 picker: Error handling pick:", error);
      this.port?.postMessage({
        type: "result",
        id: id,
        data: {
          result: "error",
          error: {
            code: "unusableItem",
            message: error instanceof Error ? error.message : "Failed to process picked items",
          },
        },
      });
    }
  }

  private handleClose(id: string): void {
    console.log("SharePoint v8 picker: Close requested");

    // Send response before closing
    this.port?.postMessage({
      type: "result",
      id: id,
      data: {
        result: "success",
      },
    });

    this.win?.close();
    this.cleanup();
  }

  private inferMimeType(filename: string): string {
    const ext = filename.split(".").pop()?.toLowerCase();
    const mimeTypes: { [key: string]: string } = {
      pdf: "application/pdf",
      doc: "application/msword",
      docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      xls: "application/vnd.ms-excel",
      xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      ppt: "application/vnd.ms-powerpoint",
      pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      txt: "text/plain",
      csv: "text/csv",
      json: "application/json",
      xml: "application/xml",
      html: "text/html",
      htm: "text/html",
      jpg: "image/jpeg",
      jpeg: "image/jpeg",
      png: "image/png",
      gif: "image/gif",
      svg: "image/svg+xml",
      webp: "image/webp",
      mp4: "video/mp4",
      mp3: "audio/mpeg",
      wav: "audio/wav",
      zip: "application/zip",
      rar: "application/x-rar-compressed",
      "7z": "application/x-7z-compressed",
    };
    return mimeTypes[ext || ""] || "application/octet-stream";
  }

  private cleanup(): void {
    // Remove message listener
    if (this.messageListener) {
      window.removeEventListener("message", this.messageListener);
      this.messageListener = null;
    }

    // Close port
    if (this.port) {
      this.port.close();
      this.port = null;
    }

    // Notify state change
    this.onPickerStateChange?.(false);

    // Clear references
    this.win = null;
    this.onFileSelected = null;
  }
}
