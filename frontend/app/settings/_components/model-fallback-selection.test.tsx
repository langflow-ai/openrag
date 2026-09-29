import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { makeSettings } from "@/test-utils/fixtures/settings";
import { renderWithProviders } from "@/test-utils/render";
import { AgentSettingsSection } from "./agent-settings-section";
import { IngestSettingsSection } from "./ingest-settings-section";

const catalog = {
  providers: [
    {
      key: "azure",
      name: "Azure OpenAI",
      models: [{ model: "gpt-4.1", capabilities: ["function_calling"] }],
      embedding_models: [
        { model: "text-embedding-3-small", mode: "embedding" },
      ],
    },
  ],
};

const settings = makeSettings({
  providers: { custom: { azure: { configured: true } } },
  agent: { llm_provider: "azure", llm_model: "" },
  knowledge: {
    embedding_provider: "azure",
    embedding_model: "",
    chunk_size: 1024,
    chunk_overlap: 50,
  },
});

function handlers(updates: unknown[]) {
  return [
    http.get("/api/settings", () => HttpResponse.json(settings)),
    http.get("/api/models/catalog", () => HttpResponse.json(catalog)),
    http.post("/api/models/openai", () =>
      HttpResponse.json({ language_models: [], embedding_models: [] }),
    ),
    http.post("/api/settings", async ({ request }) => {
      updates.push(await request.json());
      return HttpResponse.json({
        message: "Configuration updated successfully",
      });
    }),
  ];
}

const providers = ["tooltip", "auth", "brand", "unsavedChanges"] as const;

describe("Azure fallback model selection", () => {
  it("asks for an explicit language deployment instead of saving a catalog model", async () => {
    const updates: unknown[] = [];
    const user = userEvent.setup();
    renderWithProviders(<AgentSettingsSection />, {
      providers: [...providers],
      handlers: handlers(updates),
    });

    const selector = await screen.findByRole("combobox");
    await user.click(selector);
    const option = await screen.findByRole("option", { name: "gpt-4.1" });

    expect(
      screen.getByText(
        "Select or enter an Azure deployment name before chatting",
      ),
    ).toBeInTheDocument();
    expect(updates).toEqual([]);

    await user.click(option);
    await waitFor(() =>
      expect(updates).toEqual([
        { llm_model: "gpt-4.1", llm_provider: "azure" },
      ]),
    );
  });

  it("asks for an explicit embedding deployment instead of saving a catalog model", async () => {
    const updates: unknown[] = [];
    const user = userEvent.setup();
    renderWithProviders(<IngestSettingsSection />, {
      providers: [...providers],
      handlers: handlers(updates),
    });

    const selector = await screen.findByRole("combobox");
    await user.click(selector);
    const option = await screen.findByRole("option", {
      name: "text-embedding-3-small",
    });

    expect(
      screen.getByText(
        "Select or enter an Azure deployment name before ingesting files",
      ),
    ).toBeInTheDocument();
    expect(updates).toEqual([]);

    await user.click(option);
    await waitFor(() =>
      expect(updates).toEqual([
        {
          embedding_model: "text-embedding-3-small",
          embedding_provider: "azure",
        },
      ]),
    );
  });
});
