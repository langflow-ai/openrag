import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export interface DocumentAcl {
  owner: string | null;
  allowed_users: string[];
  allowed_groups: string[];
}

async function fetchDocumentAcl(filename: string): Promise<DocumentAcl> {
  const response = await fetch(
    `/api/documents/acl?filename=${encodeURIComponent(filename)}`,
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || "Failed to fetch document ACL");
  }
  return response.json();
}

export const useGetDocumentAclQuery = (
  filename: string | null | undefined,
  options?: Omit<UseQueryOptions<DocumentAcl>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  return useQuery(
    {
      queryKey: ["document-acl", filename],
      queryFn: () => fetchDocumentAcl(filename!),
      enabled: !!filename,
      ...options,
    },
    queryClient,
  );
};
