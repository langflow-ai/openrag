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
