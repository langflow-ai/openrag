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

type PickerCommand =
  | PickCommand
  | AuthenticateCommand
  | CloseCommand
  | { command: string };

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
    onPickerStateChange?: (isOpen: boolean) => void,
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
          },
        },
      };

      // Build the URL with configuration in query string
      const queryString = new URLSearchParams({
        filePicker: JSON.stringify(options),
        locale: "en-us",
      });

      const pickerUrl = `${this.baseUrl}/_layouts/15/FilePicker.aspx?${queryString}`;

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
    // Verify the message is from our picker window
    if (event.source !== this.win) {
      return;
    }

    const message = event.data;

    // Handle initialization message
    if (message.type === "initialize" && message.channelId === this.channelId) {
      // Get the MessagePort for further communication
      this.port = event.ports[0];

      if (this.port) {
        // Setup port message handler
        this.port.addEventListener(
          "message",
          this.handlePortMessage.bind(this),
        );
        this.port.start();

        // Activate the picker
        this.port.postMessage({ type: "activate" });
      } else {
        console.error(
          "SharePoint v8 picker: No MessagePort received in initialize message!",
        );
      }
    } else if (message.type === "error") {
      // === DIAGNOSTIC: Handle error messages from picker ===
      console.error(
        "SharePoint v8 picker: Error message from picker window:",
        message,
      );
    } else if (message.channelId && message.channelId !== this.channelId) {
      console.warn(
        "SharePoint v8 picker: Channel ID mismatch! Expected:",
        this.channelId,
        "Got:",
        message.channelId,
      );
    }
  }

  private handlePortMessage(event: MessageEvent): void {
    const payload = event.data;

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
    }
  }

  private handleNotification(notification: { notification: string }): void {
    if (notification.notification === "page-loaded") {
    }
  }

  private handleCommand(id: string, command: PickerCommand): void {
    // All commands must be acknowledged first
    this.port?.postMessage({
      type: "acknowledge",
      id: id,
    });

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
    // Check if resource matches our base URL or is Microsoft Graph using URL parsing
    const resourceUrl = tryParseUrl(command.resource);
    const baseUrl = tryParseUrl(this.baseUrl);

    const isGraphResource = resourceUrl
      ? isGraphHostname(resourceUrl.hostname)
      : false;
    const isSharePointResource = resourceUrl
      ? isSharePointHostname(resourceUrl.hostname)
      : false;
    const _resourceMatchesBase = hostnamesMatch(resourceUrl, baseUrl);

    if (isSharePointResource && !isGraphResource) {
      console.warn(
        "⚠️ POTENTIAL ISSUE: Picker requested SharePoint resource, but our token is for Microsoft Graph!",
      );
      console.warn("⚠️ This mismatch could cause 'invalid_client' errors.");
      console.warn(
        "⚠️ The token audience might need to be the SharePoint domain instead.",
      );
    }

    // Decode JWT header to show audience (if present)
    try {
      const tokenParts = this.accessToken?.split(".");
      if (tokenParts && tokenParts.length >= 2) {
        const _payload = JSON.parse(atob(tokenParts[1]));
      }
    } catch (_e) {}

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
    } catch (error) {
      console.error(
        "SharePoint v8 picker: Failed to provide auth token:",
        error,
      );
      this.port?.postMessage({
        type: "result",
        id: id,
        data: {
          result: "error",
          error: {
            code: "unableToObtainToken",
            message:
              error instanceof Error ? error.message : "Failed to obtain token",
          },
        },
      });
    }
  }

  private handlePick(id: string, command: PickCommand): void {
    try {
      // Convert picked items to CloudFile format
      const files: CloudFile[] = (command.items || []).map((item) => {
        // Determine mime type
        let mimeType = item.file?.mimeType;
        if (!mimeType && item.name) {
          mimeType = this.inferMimeType(item.name);
        }

        const driveId = item.parentReference?.driveId;
        const itemId = item.id;
        const finalId = driveId ? `${driveId}!${itemId}` : itemId;

        return {
          id: finalId,
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
            message:
              error instanceof Error
                ? error.message
                : "Failed to process picked items",
          },
        },
      });
    }
  }

  private handleClose(id: string): void {
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
