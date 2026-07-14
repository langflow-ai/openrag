export interface ConnectorDuplicateFile {
  id: string;
  name: string;
  mimeType: string;
  size?: number;
  downloadUrl?: string;
  webUrl?: string;
  isFolder?: boolean;
}

export interface ConnectorDuplicateCheckBody<F> {
  connection_id?: string;
  selected_files?: F[];
  bucket_filter?: string[];
}

export interface ConnectorDuplicateCheckResult<F> {
  duplicateNames: string[];
  duplicateCount: number;
  duplicateFiles: F[];
  nonDuplicateFiles: F[];
}

/** POSTs to a connector's check-duplicates endpoint and normalizes the
 * response. Shared by every ingest flow that previews duplicates before
 * syncing (individual-file selection, bucket_filter, OAuth connectors). */
export async function checkConnectorDuplicates<F = ConnectorDuplicateFile>(
  connectorType: string,
  body: ConnectorDuplicateCheckBody<F>,
): Promise<ConnectorDuplicateCheckResult<F>> {
  const response = await fetch(
    `/api/connectors/${connectorType}/check-duplicates`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );

  if (!response.ok) {
    throw new Error(`Duplicate check failed: ${response.statusText}`);
  }

  const data = await response.json();
  const duplicateNames: string[] = data.duplicate_names || [];
  const duplicateCount =
    typeof data.duplicate_count === "number"
      ? data.duplicate_count
      : duplicateNames.length;

  return {
    duplicateNames,
    duplicateCount,
    duplicateFiles: (data.duplicate_files || []) as F[],
    nonDuplicateFiles: (data.non_duplicate_files || []) as F[],
  };
}
