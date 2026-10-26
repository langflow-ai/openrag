import type { QueryClient } from "@tanstack/react-query";
import { getSettings } from "@/app/api/queries/useGetSettingsQuery";

/**
 * Whether the step can be submitted. `credentialBlocker` is a reason the
 * provider form reported (a saved secret to re-enter for a changed endpoint);
 * the backend would refuse that Submit, so it is blocked here instead.
 */
export function canCompleteOnboarding({
  isEmbedding,
  llmModel,
  embeddingModel,
  credentialBlocker = null,
}: {
  isEmbedding: boolean;
  llmModel: string;
  embeddingModel: string;
  credentialBlocker?: string | null;
}): boolean {
  if (credentialBlocker) return false;
  return isEmbedding ? !!embeddingModel : !!llmModel;
}

/** A failed first-time validation has no saved onboarding state to restore. */
export function shouldRollbackFailedOnboarding(
  configWasEdited: boolean | undefined,
): boolean {
  return configWasEdited === true;
}

/**
 * Resolve whether the just-saved config is `edited`, for the rollback check
 * above. A cached `settings` query snapshot can predate this onboarding
 * attempt: the backend marks the config `edited` as soon as it persists
 * (before sample-doc ingestion runs), but that update only reaches the
 * query cache via the onboarding mutation's `onSettled` invalidation, which
 * fires after `onError`. Fetching fresh here (bypassing the cache) ensures
 * the rollback decision reflects what this attempt actually saved.
 */
export async function fetchEditedForRollbackCheck(
  queryClient: QueryClient,
  fallbackEdited: boolean | undefined,
): Promise<boolean | undefined> {
  try {
    const settings = await queryClient.fetchQuery({
      queryKey: ["settings"],
      queryFn: getSettings,
      staleTime: 0,
      retry: false,
    });
    return settings?.edited;
  } catch {
    return fallbackEdited;
  }
}
