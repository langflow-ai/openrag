import { ChangeEvent, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { duplicateCheck, uploadFile } from "@/lib/upload-utils";

interface OnboardingUploadProps {
  onComplete: () => void;
}

const OnboardingUpload = ({ onComplete }: OnboardingUploadProps) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);

  const resetFileInput = () => {
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };


  const performUpload = async (file: File, replace = false) => {
    setIsUploading(true);
    try {
      await uploadFile(file, replace);
      console.log("Document uploaded successfully");
    } catch (error) {
      console.error("Upload failed", (error as Error).message);
    } finally {
      setIsUploading(false);
      onComplete();
    }
  };

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (!selectedFile) {
      resetFileInput();
      return;
    }

    try {
      const duplicateInfo = await duplicateCheck(selectedFile);
      if (duplicateInfo.exists) {
        console.log("Duplicate file detected");
        return;
      }

      await performUpload(selectedFile, false);
    } catch (error) {
      console.error("Unable to prepare file for upload", (error as Error).message);
    } finally {
      resetFileInput();
    }
  };


  return (
    <div className="space-y-4">
      <Button
        size="sm"
        variant="outline"
        onClick={handleUploadClick}
        disabled={isUploading}
      >
        {isUploading ? "Uploading..." : "Add a Document"}
      </Button>
      <input
        ref={fileInputRef}
        type="file"
        onChange={handleFileChange}
        className="hidden"
        accept=".pdf,.doc,.docx,.txt,.md,.rtf,.odt"
      />
    </div>
  )
}

export default OnboardingUpload;
