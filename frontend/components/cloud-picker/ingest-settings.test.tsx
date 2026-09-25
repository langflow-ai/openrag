import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { makeSettings } from "@/test-utils/fixtures/settings";
import {
  createTestQueryClient,
  renderWithProviders,
} from "@/test-utils/render";
import { IngestSettings } from "./ingest-settings";

describe("connector ingest settings", () => {
  it("keeps an empty Azure deployment unselected", async () => {
    const onSettingsChange = vi.fn();
    const settings = makeSettings({
      knowledge: {
        embedding_provider: "azure",
        embedding_model: "",
        chunk_size: 1024,
        chunk_overlap: 50,
      },
    });
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(["settings"], settings);
    queryClient.setQueryData(["models", "catalog"], {
      providers: [
        {
          key: "azure",
          name: "Azure OpenAI",
          models: [],
          embedding_models: [
            { model: "text-embedding-3-small", mode: "embedding" },
          ],
        },
      ],
    });

    renderWithProviders(
      <IngestSettings
        isOpen
        onOpenChange={() => {}}
        settings={{
          embeddingModel: "",
          chunkSize: 1024,
          chunkOverlap: 50,
          ocr: false,
          pictureDescriptions: false,
        }}
        onSettingsChange={onSettingsChange}
      />,
      {
        providers: ["tooltip", "auth"],
        auth: authPresets.unauthenticated,
        queryClient,
      },
    );

    expect(
      await screen.findByRole("combobox", {
        name: "Embedding model",
      }),
    ).toHaveTextContent("Select an embedding model");
    expect(
      screen.getByText(
        "Select an embedding model in Settings before ingesting files",
      ),
    ).toBeInTheDocument();
    expect(onSettingsChange).not.toHaveBeenCalled();
  });
});
