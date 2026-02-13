"use client";

import { CloudFile } from "./types";

/**
 * OneDrive File Picker v8 Handler for Personal OneDrive
 * 
 * Uses Microsoft's File Picker v8 which communicates via postMessage.
 * This is for personal Microsoft accounts (consumer OneDrive).
 * 
 * Reference: https://learn.microsoft.com/en-us/onedrive/developer/controls/file-pickers/
 */

interface PickerOptions {
  sdk: string;
  entry: {
    oneDrive?: {
      files?: { folder?: string };
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

export class OneDriveV8Handler {
  private win: Window | null = null;
  private port: MessagePort | null = null;
  private channelId: string;
  private accessToken: string;
  private clientId: string;
  private onFileSelected: ((files: CloudFile[]) => void) | null = null;
  private onPickerStateChange: ((isOpen: boolean) => void) | null = null;
  private messageListener: ((event: MessageEvent) => void) | null = null;

  // OneDrive personal picker URL
  private static readonly ONEDRIVE_PICKER_URL = "https://onedrive.live.com/picker";

  constructor(
    accessToken: string,
    clientId: string,
    onPickerStateChange?: (isOpen: boolean) => void
  ) {
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
    return !!(this.accessToken && this.clientId);
  }

  openPicker(onFileSelected: (files: CloudFile[]) => void): void {
    this.onFileSelected = onFileSelected;
    this.onPickerStateChange?.(true);

    try {
      // Generate a new channel ID for this picker instance
      this.channelId = this.generateUUID();

      // Open popup window (recommended size by Microsoft: 1080x680, min: 250x230)
      this.win = window.open("", "OneDrivePicker", "width=1080,height=680");

      if (!this.win) {
        console.error("Failed to open OneDrive picker popup - popup may be blocked");
        this.onPickerStateChange?.(false);
        return;
      }

      // Create picker configuration for personal OneDrive
      const options: PickerOptions = {
        sdk: "8.0",
        entry: {
          // For personal OneDrive, use oneDrive entry
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
                download: true, // Request download URLs - critical for ingestion!
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

      const pickerUrl = `${OneDriveV8Handler.ONEDRIVE_PICKER_URL}?${queryString}`;
      console.log("OneDrive v8 picker: Opening picker at", pickerUrl);

      // Create and submit form to the picker URL
      const form = this.win.document.createElement("form");
      form.setAttribute("action", pickerUrl);
      form.setAttribute("method", "POST");

      // Add access token as hidden input
      const tokenInput = this.win.document.createElement("input");
      tokenInput.setAttribute("type", "hidden");
      tokenInput.setAttribute("name", "access_token");
      tokenInput.setAttribute("value", this.accessToken);
      form.appendChild(tokenInput);

      // Append form to popup body and submit
      this.win.document.body.appendChild(form);
      form.submit();

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
      console.error("Error opening OneDrive v8 picker:", error);
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
      console.log("OneDrive v8 picker: Received initialize message");

      // Get the MessagePort for further communication
      this.port = event.ports[0];

      if (this.port) {
        // Setup port message handler
        this.port.addEventListener("message", this.handlePortMessage.bind(this));
        this.port.start();

        // Activate the picker
        this.port.postMessage({ type: "activate" });
        console.log("OneDrive v8 picker: Activated");
      }
    }
  }

  private handlePortMessage(event: MessageEvent): void {
    const payload = event.data;
    console.log("OneDrive v8 picker: Port message received:", payload.type);

    switch (payload.type) {
      case "notification":
        this.handleNotification(payload.data);
        break;

      case "command":
        this.handleCommand(payload.id, payload.data);
        break;
    }
  }

  private handleNotification(notification: { notification: string }): void {
    console.log("OneDrive v8 picker: Notification:", notification.notification);

    if (notification.notification === "page-loaded") {
      console.log("OneDrive v8 picker: Page loaded and ready");
    }
  }

  private handleCommand(id: string, command: PickerCommand): void {
    // All commands must be acknowledged first
    this.port?.postMessage({
      type: "acknowledge",
      id: id,
    });

    console.log("OneDrive v8 picker: Command:", command.command);

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
    console.log("OneDrive v8 picker: Auth request for resource:", command.resource);

    // For now, we use the same token for all requests
    // The token should be a Microsoft Graph token with Files.Read scope
    try {
      this.port?.postMessage({
        type: "result",
        id: id,
        data: {
          result: "token",
          token: this.accessToken,
        },
      });
      console.log("OneDrive v8 picker: Provided auth token");
    } catch (error) {
      console.error("OneDrive v8 picker: Failed to provide auth token:", error);
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
    console.log("OneDrive v8 picker: Files picked:", command.items?.length);

    try {
      // Convert picked items to CloudFile format
      const files: CloudFile[] = (command.items || []).map((item) => {
        // Determine mime type
        let mimeType = item.file?.mimeType;
        if (!mimeType && item.name) {
          mimeType = this.inferMimeType(item.name);
        }

        // Log the download URL for debugging
        const downloadUrl = item["@microsoft.graph.downloadUrl"] || "";
        console.log(`OneDrive v8 picker: File "${item.name}" downloadUrl: ${downloadUrl ? "present" : "MISSING"}`);

        return {
          id: item.id,
          name: item.name || "Unknown",
          mimeType: mimeType || "application/octet-stream",
          webUrl: item.webUrl || "",
          downloadUrl: downloadUrl,
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
      console.error("OneDrive v8 picker: Error handling pick:", error);
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
    console.log("OneDrive v8 picker: Close requested");

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
