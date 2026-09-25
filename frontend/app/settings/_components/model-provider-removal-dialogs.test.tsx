import { HttpResponse, http } from "msw";
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";
import type { UpdateSettingsRequest } from "@/app/api/mutations/useUpdateSettingsMutation";
import { makeSettings } from "@/test-utils/fixtures/settings";
import {
  renderWithProviders,
  screen,
  userEvent,
  waitFor,
} from "@/test-utils/render";
import OllamaSettingsDialog from "./ollama-settings-dialog";
import OpenAISettingsDialog from "./openai-settings-dialog";
import WatsonxSettingsDialog from "./watsonx-settings-dialog";

const settings = makeSettings({
  providers: {
    openai: { configured: true },
    watsonx: { configured: true },
    ollama: { configured: true, endpoint: "http://localhost:11434" },
    custom: {
      azure: {
        configured: true,
        credential_values: {},
        secret_fields: ["api_key"],
      },
    },
  },
  agent: { llm_provider: "openai" },
});

const dialogs: Array<{
  name: string;
  dialog: ReactElement;
  removal: UpdateSettingsRequest;
}> = [
  {
    name: "OpenAI",
    dialog: <OpenAISettingsDialog open setOpen={() => {}} />,
    removal: { remove_openai_config: true },
  },
  {
    name: "Ollama",
    dialog: <OllamaSettingsDialog open setOpen={() => {}} />,
    removal: { remove_ollama_config: true },
  },
  {
    name: "IBM watsonx.ai",
    dialog: <WatsonxSettingsDialog open setOpen={() => {}} />,
    removal: { remove_watsonx_config: true },
  },
];

describe.each(dialogs)("$name provider removal", ({ dialog, removal }) => {
  it("requires explicit confirmation when embedding usage cannot be determined", async () => {
    const submissions: UpdateSettingsRequest[] = [];

    renderWithProviders(dialog, {
      providers: ["auth", "tooltip"],
      handlers: [
        http.get("/api/settings", () => HttpResponse.json(settings)),
        http.post("/api/models/openai", () =>
          HttpResponse.json({ language_models: [], embedding_models: [] }),
        ),
        http.post("/api/settings", async ({ request }) => {
          const submission = (await request.json()) as UpdateSettingsRequest;
          submissions.push(submission);
          if (!submission.force_remove) {
            return HttpResponse.json(
              {
                error: "Embedding usage could not be determined.",
                code: "embedding_usage_unknown",
                affected_provider: "provider",
              },
              { status: 503 },
            );
          }
          return HttpResponse.json({ message: "saved", settings });
        }),
      ],
    });

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Remove" }));
    await user.click(screen.getByRole("button", { name: "Remove" }));

    expect(
      await screen.findByText(
        /Could not verify whether indexed documents use this provider/,
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Remove" }));
    await user.click(screen.getByRole("button", { name: "Remove" }));
    await screen.findByText(
      /Could not verify whether indexed documents use this provider/,
    );

    await user.click(
      await screen.findByRole("button", { name: /Remove anyway/i }),
    );

    await waitFor(() => {
      expect(submissions).toEqual([
        { ...removal, force_remove: false },
        { ...removal, force_remove: false },
        { ...removal, force_remove: true },
      ]);
    });
  });
});

it("OpenAI preserves the confirmed-usage warning", async () => {
  renderWithProviders(<OpenAISettingsDialog open setOpen={() => {}} />, {
    providers: ["auth", "tooltip"],
    handlers: [
      http.get("/api/settings", () => HttpResponse.json(settings)),
      http.post("/api/models/openai", () =>
        HttpResponse.json({ language_models: [], embedding_models: [] }),
      ),
      http.post("/api/settings", () =>
        HttpResponse.json(
          {
            error: "Embedding provider is in use.",
            code: "embedding_provider_in_use",
            affected_provider: "openai",
            affected_models: [
              { model: "text-embedding-3-small", doc_count: 4 },
            ],
          },
          { status: 409 },
        ),
      ),
    ],
  });

  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Remove" }));
  await user.click(screen.getByRole("button", { name: "Remove" }));

  expect(await screen.findByText("text-embedding-3-small")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /Remove anyway/i }),
  ).toBeInTheDocument();
});
