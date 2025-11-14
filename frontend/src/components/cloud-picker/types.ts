export interface CloudFile {
  id: string;
  name: string;
  mimeType: string;
  webViewLink?: string;
  iconLink?: string;
  size?: number;
  modifiedTime?: string;
  isFolder?: boolean;
  webUrl?: string;
  downloadUrl?: string;
}

export type CloudProvider = "google_drive" | "onedrive" | "sharepoint";

export interface UnifiedCloudPickerProps {
  provider: CloudProvider;
  onFileSelected: (files: CloudFile[]) => void;
  selectedFiles?: CloudFile[];
  isAuthenticated: boolean;
  accessToken?: string;
  onPickerStateChange?: (isOpen: boolean) => void;
  // OneDrive/SharePoint specific props
  clientId?: string;
  baseUrl?: string;
  // Ingest settings
  onSettingsChange?: (settings: IngestSettings) => void;
  isIngesting: boolean;
}

export interface GoogleAPI {
  load: (
    api: string,
    options: { callback: () => void; onerror?: () => void },
  ) => void;
}

export interface GooglePickerData {
  action: string;
  docs: GooglePickerDocument[];
}

export interface GooglePickerDocument {
  [key: string]: string;
}

declare global {
  interface Window {
    gapi: GoogleAPI;
    google: {
      picker: {
        api: {
          load: (callback: () => void) => void;
        };
        PickerBuilder: new () => GooglePickerBuilder;
        DocsView: new () => GoogleDocsView;
        ViewId: {
          DOCS: string;
          FOLDERS: string;
          DOCS_IMAGES_AND_VIDEOS: string;
          DOCUMENTS: string;
          PRESENTATIONS: string;
          SPREADSHEETS: string;
        };
        Feature: {
          MULTISELECT_ENABLED: string;
          NAV_HIDDEN: string;
          SIMPLE_UPLOAD_ENABLED: string;
        };
        Action: {
          PICKED: string;
          CANCEL: string;
        };
        Document: {
          ID: string;
          NAME: string;
          MIME_TYPE: string;
          URL: string;
          ICON_URL: string;
        };
      };
    };
    OneDrive?: any;
  }
}

export interface GoogleDocsView {
  setIncludeFolders: (include: boolean) => GoogleDocsView;
  setSelectFolderEnabled: (enabled: boolean) => GoogleDocsView;
}

export interface GooglePickerBuilder {
  addView: (view: GoogleDocsView | string) => GooglePickerBuilder;
  setOAuthToken: (token: string) => GooglePickerBuilder;
  setCallback: (
    callback: (data: GooglePickerData) => void,
  ) => GooglePickerBuilder;
  enableFeature: (feature: string) => GooglePickerBuilder;
  setTitle: (title: string) => GooglePickerBuilder;
  build: () => GooglePicker;
}

export interface GooglePicker {
  setVisible: (visible: boolean) => void;
}

export interface IngestSettings {
  chunkSize: number;
  chunkOverlap: number;
  ocr: boolean;
  pictureDescriptions: boolean;
  embeddingModel: string;
}
