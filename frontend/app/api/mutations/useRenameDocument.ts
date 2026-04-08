import { useMutation } from "@tanstack/react-query";

interface RenameDocumentParams {
  oldFilename: string;
  newFilename: string;
}

interface RenameDocumentResult {
  success: boolean;
  updated_chunks: number;
  old_filename: string;
  new_filename: string;
}

export function useRenameDocument() {
  return useMutation<RenameDocumentResult, Error, RenameDocumentParams>({
    mutationFn: async ({ oldFilename, newFilename }) => {
      const response = await fetch("/documents/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          old_filename: oldFilename,
          new_filename: newFilename,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || "Failed to rename document");
      }

      return response.json();
    },
  });
}
