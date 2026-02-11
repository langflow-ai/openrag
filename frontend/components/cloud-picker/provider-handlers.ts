"use client";

import {
  CloudFile,
  CloudProvider,
  GooglePickerData,
  GooglePickerDocument,
} from "./types";
import { SharePointV8Handler } from "./sharepoint-v8-handler";

export class GoogleDriveHandler {
  private accessToken: string;
  private onPickerStateChange?: (isOpen: boolean) => void;

  constructor(
    accessToken: string,
    onPickerStateChange?: (isOpen: boolean) => void,
  ) {
    this.accessToken = accessToken;
    this.onPickerStateChange = onPickerStateChange;
  }

  async loadPickerApi(): Promise<boolean> {
    return new Promise((resolve) => {
      if (typeof window !== "undefined" && window.gapi) {
        window.gapi.load("picker", {
          callback: () => resolve(true),
          onerror: () => resolve(false),
        });
      } else {
        // Load Google API script
        const script = document.createElement("script");
        script.src = "https://apis.google.com/js/api.js";
        script.async = true;
        script.defer = true;
        script.onload = () => {
          window.gapi.load("picker", {
            callback: () => resolve(true),
            onerror: () => resolve(false),
          });
        };
        script.onerror = () => resolve(false);
        document.head.appendChild(script);
      }
    });
  }

  openPicker(onFileSelected: (files: CloudFile[]) => void): void {
    if (!window.google?.picker) {
      return;
    }

    try {
      this.onPickerStateChange?.(true);

      // Create a view for regular documents
      const docsView = new window.google.picker.DocsView()
        .setIncludeFolders(true)
        .setSelectFolderEnabled(true);

      const picker = new window.google.picker.PickerBuilder()
        .addView(docsView)
        .setOAuthToken(this.accessToken)
        .enableFeature(window.google.picker.Feature.MULTISELECT_ENABLED)
        .setTitle("Select files or folders from Google Drive")
        .setCallback((data) => this.pickerCallback(data, onFileSelected))
        .build();

      picker.setVisible(true);

      // Apply z-index fix
      setTimeout(() => {
        const pickerElements = document.querySelectorAll(
          ".picker-dialog, .goog-modalpopup",
        );
        pickerElements.forEach((el) => {
          (el as HTMLElement).style.zIndex = "10000";
        });
        const bgElements = document.querySelectorAll(
          ".picker-dialog-bg, .goog-modalpopup-bg",
        );
        bgElements.forEach((el) => {
          (el as HTMLElement).style.zIndex = "9999";
        });
      }, 100);
    } catch (error) {
      console.error("Error creating picker:", error);
      this.onPickerStateChange?.(false);
    }
  }

  private async pickerCallback(
    data: GooglePickerData,
    onFileSelected: (files: CloudFile[]) => void,
  ): Promise<void> {
    if (data.action === window.google.picker.Action.PICKED) {
      const files: CloudFile[] = data.docs.map((doc: GooglePickerDocument) => ({
        id: doc[window.google.picker.Document.ID],
        name: doc[window.google.picker.Document.NAME],
        mimeType: doc[window.google.picker.Document.MIME_TYPE],
        webViewLink: doc[window.google.picker.Document.URL],
        iconLink: doc[window.google.picker.Document.ICON_URL],
        size: doc["sizeBytes"] ? parseInt(doc["sizeBytes"]) : undefined,
        modifiedTime: doc["lastEditedUtc"],
        isFolder:
          doc[window.google.picker.Document.MIME_TYPE] ===
          "application/vnd.google-apps.folder",
      }));

      // Enrich with additional file data if needed
      if (files.some((f) => !f.size && !f.isFolder)) {
        try {
          const enrichedFiles = await Promise.all(
            files.map(async (file) => {
              if (!file.size && !file.isFolder) {
                try {
                  const response = await fetch(
                    `https://www.googleapis.com/drive/v3/files/${file.id}?fields=size,modifiedTime`,
                    {
                      headers: {
                        Authorization: `Bearer ${this.accessToken}`,
                      },
                    },
                  );
                  if (response.ok) {
                    const fileDetails = await response.json();
                    return {
                      ...file,
                      size: fileDetails.size
                        ? parseInt(fileDetails.size)
                        : undefined,
                      modifiedTime:
                        fileDetails.modifiedTime || file.modifiedTime,
                    };
                  }
                } catch (error) {
                  console.warn("Failed to fetch file details:", error);
                }
              }
              return file;
            }),
          );
          onFileSelected(enrichedFiles);
        } catch (error) {
          console.warn("Failed to enrich file data:", error);
          onFileSelected(files);
        }
      } else {
        onFileSelected(files);
      }
    }

    this.onPickerStateChange?.(false);
  }
}

export class OneDriveHandler {
  private accessToken: string;
  private clientId: string;
  private provider: CloudProvider;
  private baseUrl?: string;

  constructor(
    accessToken: string,
    clientId: string,
    provider: CloudProvider = "onedrive",
    baseUrl?: string,
  ) {
    this.accessToken = accessToken;
    this.clientId = clientId;
    this.provider = provider;
    this.baseUrl = baseUrl;
  }

  async loadPickerApi(): Promise<boolean> {
    return new Promise((resolve) => {
      const script = document.createElement("script");
      script.src = "https://js.live.net/v7.2/OneDrive.js";
      script.onload = () => resolve(true);
      script.onerror = () => resolve(false);
      document.head.appendChild(script);
    });
  }

  openPicker(onFileSelected: (files: CloudFile[]) => void): void {
    if (!window.OneDrive) {
      return;
    }

    // For SharePoint, use the SharePoint site URL as endpoint hint
    // For OneDrive, use the default OneDrive API endpoint
    const endpointHint = this.provider === "sharepoint" && this.baseUrl
      ? this.baseUrl
      : "api.onedrive.com";

    window.OneDrive.open({
      clientId: this.clientId,
      action: "query",
      multiSelect: true,
      advanced: {
        endpointHint: endpointHint,
        accessToken: this.accessToken,
      },
      success: (response: any) => {
        console.log("OneDrive picker success callback:", response);
        if (!response || !response.value) {
          console.warn("OneDrive picker returned no value");
          return;
        }
        
        const newFiles: CloudFile[] =
          response.value?.map((item: any) => {
            // Extract mimeType from file object or infer from name
            let mimeType = item.file?.mimeType;
            if (!mimeType && item.name) {
              // Infer from extension if mimeType not provided
              const ext = item.name.split(".").pop()?.toLowerCase();
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
                jpg: "image/jpeg",
                jpeg: "image/jpeg",
                png: "image/png",
                gif: "image/gif",
                svg: "image/svg+xml",
              };
              mimeType = mimeTypes[ext || ""] || "application/octet-stream";
            }

            return {
              id: item.id,
              name: item.name || `${this.getProviderName()} File`,
              mimeType: mimeType || "application/octet-stream",
              webUrl: item.webUrl || "",
              downloadUrl: item["@microsoft.graph.downloadUrl"] || "",
              size: item.size,
              modifiedTime: item.lastModifiedDateTime,
              isFolder: !!item.folder,
            };
          }) || [];

        onFileSelected(newFiles);
      },
      cancel: () => {
        console.log("Picker cancelled");
      },
      error: (error: any) => {
        console.error("Picker error callback:", error);
      },
    });
  }

  private getProviderName(): string {
    return this.provider === "sharepoint" ? "SharePoint" : "OneDrive";
  }
}

export const createProviderHandler = (
  provider: CloudProvider,
  accessToken: string,
  onPickerStateChange?: (isOpen: boolean) => void,
  clientId?: string,
  baseUrl?: string,
) => {
  // === DIAGNOSTIC LOGGING ===
  console.log("=== Creating Provider Handler ===");
  console.log("Provider:", provider);
  console.log("Client ID:", clientId);
  console.log("Base URL:", baseUrl);
  console.log("Access Token (first 20 chars):", accessToken?.substring(0, 20) + "...");
  console.log("Access Token length:", accessToken?.length);
  
  switch (provider) {
    case "google_drive":
      return new GoogleDriveHandler(accessToken, onPickerStateChange);
    case "sharepoint":
      // Use v8 File Picker for SharePoint - v7.2 has "Knockout deprecated" bug
      // making Select/Cancel buttons unresponsive
      if (!clientId) {
        throw new Error("Client ID required for SharePoint");
      }
      if (!baseUrl) {
        throw new Error("Base URL required for SharePoint v8 picker");
      }
      console.log("Creating SharePointV8Handler with baseUrl:", baseUrl);
      return new SharePointV8Handler(baseUrl, accessToken, clientId, onPickerStateChange);

    case "onedrive":
      // Use v7.2 (OneDrive.js) for personal OneDrive - v8 doesn't work for consumer accounts
      // Backend uses /shares API to handle the sharing IDs that v7.2 returns
      if (!clientId) {
        throw new Error("Client ID required for OneDrive");
      }
      return new OneDriveHandler(accessToken, clientId, provider, baseUrl);
    default:
      throw new Error(`Unsupported provider: ${provider}`);
  }
};
