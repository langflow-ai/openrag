import { delay, HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type { ProviderSettings } from "@/app/api/queries/useGetSettingsQuery";
import { makeSettings } from "@/test-utils/fixtures/settings";
import { renderWithProviders, screen, waitFor } from "@/test-utils/render";
import OnboardingCard from "./onboarding-card";

const ALL_PROVIDERS = [
  { name: "anthropic", display_name: "Anthropic" },
  { name: "openai", display_name: "OpenAI" },
  { name: "watsonx", display_name: "IBM watsonx.ai" },
  { name: "ollama", display_name: "Ollama" },
  { name: "openai_like", display_name: "Other provider" },
];

function renderCard({
  providers = ALL_PROVIDERS,
  settingsProviders = {},
  providersDelayMs = 0,
}: {
  providers?: { name: string; display_name: string }[];
  settingsProviders?: ProviderSettings;
  providersDelayMs?: number;
} = {}) {
  renderWithProviders(<OnboardingCard onComplete={() => {}} />, {
    providers: ["tooltip"],
    handlers: [
      http.get("/api/models/providers", async () => {
        if (providersDelayMs) await delay(providersDelayMs);
        return HttpResponse.json({ run_mode: "oss", providers });
      }),
      http.get("/api/models/catalog", () =>
        HttpResponse.json({ providers: [] }),
      ),
      http.get("/api/settings", () =>
        HttpResponse.json(makeSettings({ providers: settingsProviders })),
      ),
      http.all("/api/models/*", () =>
        HttpResponse.json({ language_models: [], embedding_models: [] }),
      ),
    ],
  });
}

async function expectSelectedTab(name: string) {
  // The accessible name also carries the logo's SVG title, so match the label it ends with.
  const tab = await screen.findByRole("tab", {
    name: (accessibleName) => accessibleName.endsWith(name),
  });
  await waitFor(() => expect(tab).toHaveAttribute("aria-selected", "true"));
}

describe("OnboardingCard provider selection", () => {
  it("falls back to the first offered provider when the default is not offered", async () => {
    renderCard({
      providers: [
        { name: "openai", display_name: "OpenAI" },
        { name: "ollama", display_name: "Ollama" },
      ],
    });
    await expectSelectedTab("OpenAI");
  });

  it.each([
    {
      expected: "Anthropic",
      settingsProviders: { anthropic: { has_api_key: true } },
    },
    {
      expected: "OpenAI",
      settingsProviders: { openai: { has_api_key: true } },
    },
    {
      expected: "IBM watsonx.ai",
      settingsProviders: { watsonx: { has_api_key: true } },
    },
    {
      expected: "Ollama",
      settingsProviders: { ollama: { endpoint: "http://localhost:11434" } },
    },
    {
      expected: "Other provider",
      settingsProviders: { custom: { openai_like: { configured: true } } },
    },
  ] satisfies {
    expected: string;
    settingsProviders: ProviderSettings;
  }[])("selects $expected when it is the first configured provider", async ({
    expected,
    settingsProviders,
  }) => {
    renderCard({ settingsProviders });
    await expectSelectedTab(expected);
  });

  it("still auto-selects when settings load before the provider list", async () => {
    renderCard({
      settingsProviders: { ollama: { endpoint: "http://localhost:11434" } },
      providersDelayMs: 100,
    });
    await expectSelectedTab("Ollama");
  });
});
