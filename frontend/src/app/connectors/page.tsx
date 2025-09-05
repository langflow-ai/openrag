"use client"

import React, { useState } from "react";
import { GoogleDrivePicker } from "@/components/google-drive-picker"

interface GoogleDriveFile {
  id: string;
  name: string;
  mimeType: string;
  webViewLink?: string;
  iconLink?: string;
}

export default function ConnectorsPage() {
  const [selectedFiles, setSelectedFiles] = useState<GoogleDriveFile[]>([]);

  const handleFileSelection = (files: GoogleDriveFile[]) => {
    setSelectedFiles(files);
  };

  const handleSync = () => {
    const fileIds = selectedFiles.map(file => file.id);
    const body = {
      file_ids: fileIds,
      folder_ids: [], // Add folder handling if needed
      recursive: true,
    };
    
    console.log('Syncing with:', body);
  };

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-4">Connectors</h1>
      
      <div className="mb-6">
        <p className="text-sm text-gray-600 mb-4">
          This is a demo page for the Google Drive picker component. 
          For full connector functionality, visit the Settings page.
        </p>
        
        <GoogleDrivePicker 
          onFileSelected={handleFileSelection}
          selectedFiles={selectedFiles}
          isAuthenticated={false} // This would come from auth context in real usage
          accessToken={undefined} // This would come from connected account
        />
      </div>

      {selectedFiles.length > 0 && (
        <button 
          onClick={handleSync}
          className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
        >
          Sync {selectedFiles.length} Selected Items
        </button>
      )}
    </div>
  );
}
