import { useEffect, useRef, useState } from "react";

/**
 * Hook to detect when files are being dragged into the browser window.
 * Optionally handles the actual drop and calls `onFileDrop` with the first
 * dropped file.
 *
 * @param onFileDrop - Optional callback invoked with the dropped File
 * @returns isDragging - true while files are being dragged over the window
 */
export function useFileDrag(onFileDrop?: (file: File) => void) {
  const [isDragging, setIsDragging] = useState(false);
  const onFileDropRef = useRef(onFileDrop);
  onFileDropRef.current = onFileDrop;

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
      dragCounter = Math.max(0, dragCounter - 1);
      if (dragCounter === 0) {
        setIsDragging(false);
      }
    };

    const handleDragOver = (e: DragEvent) => {
      e.preventDefault();
    };

    const handleDrop = (e: DragEvent) => {
      dragCounter = 0;
      setIsDragging(false);

      if (onFileDropRef.current && e.dataTransfer?.files.length) {
        e.preventDefault();
        const file = e.dataTransfer.files[0];
        if (file) {
          onFileDropRef.current(file);
        }
      }
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
