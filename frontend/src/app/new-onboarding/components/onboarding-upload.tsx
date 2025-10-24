import { ChangeEvent, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { uploadFileForContext } from "@/lib/upload-utils";
import { AnimatePresence, motion } from "motion/react";
import { AnimatedProviderSteps } from "@/app/onboarding/components/animated-provider-steps";

interface OnboardingUploadProps {
  onComplete: () => void;
}

const OnboardingUpload = ({ onComplete }: OnboardingUploadProps) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [currentStep, setCurrentStep] = useState<number | null>(null);

  const STEP_LIST = [
    "Uploading your document",
    "Processing your document",
  ];

  const resetFileInput = () => {
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const performUpload = async (file: File) => {
    setIsUploading(true);
    try {
      setCurrentStep(0);
      await uploadFileForContext(file);
      console.log("Document uploaded successfully");
    } catch (error) {
      console.error("Upload failed", (error as Error).message);
    } finally {
      setIsUploading(false);
      await new Promise(resolve => setTimeout(resolve, 1000));
      setCurrentStep(STEP_LIST.length);
      await new Promise(resolve => setTimeout(resolve, 500));
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
      await performUpload(selectedFile);
    } catch (error) {
      console.error("Unable to prepare file for upload", (error as Error).message);
    } finally {
      resetFileInput();
    }
  };


  return (
    <AnimatePresence mode="wait">
      {currentStep === null ? (
        <motion.div
          key="user-ingest"
          initial={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -24 }}
          transition={{ duration: 0.4, ease: "easeInOut" }}
        >
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
        </motion.div>
      ) : (
        <motion.div
          key="ingest-steps"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: "easeInOut" }}
        >
          <AnimatedProviderSteps
            currentStep={currentStep}
            setCurrentStep={setCurrentStep}
            steps={STEP_LIST}
          />
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default OnboardingUpload;
