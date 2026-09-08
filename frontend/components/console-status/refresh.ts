/** Refresh All: always refresh backend status. Provider health refetch()
 *  ignores `enabled` and would 403 / hit the API during onboarding or
 *  ingestion, so only call it when that query is actually enabled. */
export function refreshConsoleStatusQueries(
  refetchStatus: () => unknown,
  refetchProviderHealth: () => unknown,
  isProviderQueryEnabled: boolean,
): void {
  void refetchStatus();
  if (isProviderQueryEnabled) {
    void refetchProviderHealth();
  }
}
