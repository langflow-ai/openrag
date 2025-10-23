export interface DuplicateCheckResponse {
  exists: boolean;
  [key: string]: unknown;
}

export interface UploadFileResult {
  fileId: string;
  filePath: string;
  run: unknown;
  deletion: unknown;
  unified: boolean;
  raw: unknown;
}

export async function duplicateCheck(
  file: File
): Promise<DuplicateCheckResponse> {
  const response = await fetch(
    `/api/documents/check-filename?filename=${encodeURIComponent(file.name)}`
  );

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(
      errorText || `Failed to check duplicates: ${response.statusText}`
    );
  }

  return response.json();
}

export async function uploadFile(
  file: File,
  replace = false
): Promise<UploadFileResult> {
  window.dispatchEvent(
    new CustomEvent("fileUploadStart", {
      detail: { filename: file.name },
    })
  );

  try {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("replace_duplicates", replace.toString());

    const uploadResponse = await fetch("/api/router/upload_ingest", {
      method: "POST",
      body: formData,
    });

    let payload: unknown;
    try {
      payload = await uploadResponse.json();
    } catch (error) {
      throw new Error("Upload failed: unable to parse server response");
    }

    const uploadIngestJson =
      typeof payload === "object" && payload !== null ? payload : {};

    if (!uploadResponse.ok) {
      const errorMessage =
        (uploadIngestJson as { error?: string }).error ||
        "Upload and ingest failed";
      throw new Error(errorMessage);
    }

    const fileId =
      (uploadIngestJson as { upload?: { id?: string } }).upload?.id ||
      (uploadIngestJson as { id?: string }).id ||
      (uploadIngestJson as { task_id?: string }).task_id;
    const filePath =
      (uploadIngestJson as { upload?: { path?: string } }).upload?.path ||
      (uploadIngestJson as { path?: string }).path ||
      "uploaded";
    const runJson = (uploadIngestJson as { ingestion?: unknown }).ingestion;
    const deletionJson = (uploadIngestJson as { deletion?: unknown }).deletion;

    if (!fileId) {
      throw new Error("Upload successful but no file id returned");
    }

    if (
      runJson &&
      typeof runJson === "object" &&
      "status" in (runJson as Record<string, unknown>) &&
      (runJson as { status?: string }).status !== "COMPLETED" &&
      (runJson as { status?: string }).status !== "SUCCESS"
    ) {
      const errorMsg =
        (runJson as { error?: string }).error ||
        "Ingestion pipeline failed";
      throw new Error(
        `Ingestion failed: ${errorMsg}. Try setting DISABLE_INGEST_WITH_LANGFLOW=true if you're experiencing Langflow component issues.`
      );
    }

    const result: UploadFileResult = {
      fileId,
      filePath,
      run: runJson,
      deletion: deletionJson,
      unified: true,
      raw: uploadIngestJson,
    };

    window.dispatchEvent(
      new CustomEvent("fileUploaded", {
        detail: {
          file,
          result: {
            file_id: fileId,
            file_path: filePath,
            run: runJson,
            deletion: deletionJson,
            unified: true,
          },
        },
      })
    );

    return result;
  } catch (error) {
    window.dispatchEvent(
      new CustomEvent("fileUploadError", {
        detail: {
          filename: file.name,
          error:
            error instanceof Error ? error.message : "Upload failed",
        },
      })
    );
    throw error;
  } finally {
    window.dispatchEvent(new CustomEvent("fileUploadComplete"));
  }
}
