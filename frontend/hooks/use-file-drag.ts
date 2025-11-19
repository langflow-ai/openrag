import { useEffect, useState } from "react";

/**
 * Hook to detect when files are being dragged into the browser window
 * @returns isDragging - true when files are being dragged over the window
 */
export function useFileDrag() {
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => {
    let dragCounter = 0;

    const handleDragEnter = (e: DragEvent) => {
      // Only detect file drags
      if (e.dataTransfer?.types.includes("Files")) {
        dragCounter++;
        if (dragCounter === 1) {
          setIsDragging(true);
        }
      }
    };

    const handleDragLeave = () => {
      dragCounter--;
      if (dragCounter === 0) {
        setIsDragging(false);
      }
    };

    const handleDragOver = (e: DragEvent) => {
      e.preventDefault();
    };

    const handleDrop = () => {
      dragCounter = 0;
      setIsDragging(false);
    };

    window.addEventListener("dragenter", handleDragEnter);
    window.addEventListener("dragleave", handleDragLeave);
    window.addEventListener("dragover", handleDragOver);
    window.addEventListener("drop", handleDrop);

    return () => {
      window.removeEventListener("dragenter", handleDragEnter);
      window.removeEventListener("dragleave", handleDragLeave);
      window.removeEventListener("dragover", handleDragOver);
      window.removeEventListener("drop", handleDrop);
    };
  }, []);

  return isDragging;
}
