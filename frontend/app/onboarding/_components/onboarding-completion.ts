export function canCompleteOnboarding({
  isEmbedding,
  llmModel,
  embeddingModel,
}: {
  isEmbedding: boolean;
  llmModel: string;
  embeddingModel: string;
}): boolean {
  return isEmbedding ? !!embeddingModel : !!llmModel;
}

/** A failed first-time validation has no saved onboarding state to restore. */
export function shouldRollbackFailedOnboarding(
  configWasEdited: boolean | undefined,
): boolean {
  return configWasEdited === true;
}
