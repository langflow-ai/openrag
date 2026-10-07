/**
 * GeminiOnboarding tests.
 *
 * Three concerns:
 *
 * 1. Hidden by default — the onboarding card must not render a Gemini tab
 *    when the providers API omits it (OPENRAG_GEMINI not set).
 * 2. API key wires into shared settings — typing a key updates
 *    `provider_credentials.gemini.api_key` on the parent state.
 * 3. Embedding mode — selecting an embedding model sets both
 *    `embedding_model` and `embedding_provider: "gemini"`.
 * 4. "In development" badge — when the providers API sends the badge the
 *    tab renders it, matching the on-prem badge pattern.
 */

import { HttpResponse, http } from "msw";
import type { Dispatch, SetStateAction } from "react";
import { describe, expect, it } from "vitest";
import type { OnboardingVariables } from "@/app/api/mutations/useOnboardingMutation";
import {
  renderWithProviders,
  screen,
  userEvent,
  waitFor,
} from "@/test-utils/render";
import { GeminiOnboarding } from "./gemini-onboarding";
import OnboardingCard from "./onboarding-card";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Minimal catalog with a gemini language and embedding model. */
const geminiCatalog = {
  providers: [
    {
      key: "gemini",
      name: "Google Gemini",
      credential_fields: [
        {
          key: "api_key",
          label: "Gemini API key",
          required: true,
          field_type: "password",
        },
      ],
      models: [
        { model: "gemini-2.0-flash", capabilities: ["function_calling"] },
      ],
      embedding_models: [{ model: "text-embedding-004" }],
    },
  ],
};

/** MSW handler that returns gemini as the only provider. */
function geminiProvidersHandler(badge?: string) {
  return http.get("/api/models/providers", () =>
    HttpResponse.json({
      run_mode: "oss",
      providers: [
        {
          name: "gemini",
          display_name: "Google Gemini",
          ...(badge ? { badge } : {}),
        },
      ],
    }),
  );
}

/** MSW handler that returns an empty providers list (no gemini). */
const noGeminiProvidersHandler = http.get("/api/models/providers", () =>
  HttpResponse.json({ run_mode: "oss", providers: [] }),
);

/** Renders OnboardingCard and returns the accumulated settings. */
function renderCard(
  isEmbedding = false,
  handlers: Parameters<typeof renderWithProviders>[1]["handlers"] = [],
) {
  renderWithProviders(
    <OnboardingCard onComplete={() => {}} isEmbedding={isEmbedding} />,
    {
      providers: ["tooltip"],
      handlers,
    },
  );
}

/** Renders GeminiOnboarding directly and returns the settings spy. */
function renderGemini(
  isEmbedding = false,
  hasEnvApiKey = false,
): {
  user: ReturnType<typeof userEvent.setup>;
  getSettings: () => OnboardingVariables;
} {
  let settings: OnboardingVariables = {};
  const setSettings: Dispatch<SetStateAction<OnboardingVariables>> = (next) => {
    settings = typeof next === "function" ? next(settings) : next;
  };
  const user = userEvent.setup();
  renderWithProviders(
    <GeminiOnboarding
      setSettings={setSettings}
      isEmbedding={isEmbedding}
      hasEnvApiKey={hasEnvApiKey}
    />,
    {
      providers: ["tooltip"],
      handlers: [
        http.get("/api/models/catalog", () => HttpResponse.json(geminiCatalog)),
        // ModelSelector (inside AdvancedOnboarding) calls this for provider badges.
        geminiProvidersHandler(),
      ],
    },
  );
  return { user, getSettings: () => settings };
}

// ── 1. Hidden by default ──────────────────────────────────────────────────────

describe("OnboardingCard — gemini tab visibility", () => {
  it("does not render a gemini tab when the providers API omits it", async () => {
    renderCard(false, [
      noGeminiProvidersHandler,
      http.get("/api/models/catalog", () =>
        HttpResponse.json({ providers: [] }),
      ),
      http.get("/api/settings", () =>
        HttpResponse.json({
          onboarding: { current_step: 4 },
          providers: {},
          knowledge: {},
          agent: {},
        }),
      ),
    ]);

    // Give the query time to resolve; the absence of the tab is the assertion.
    // The card renders a "Complete" button when providers load, so wait for that.
    await screen.findByTestId("onboarding-complete-button");
    expect(screen.queryByTestId("gemini-llm-tab")).toBeNull();
  });

  it("renders a gemini tab when the providers API includes it", async () => {
    renderCard(false, [
      geminiProvidersHandler(),
      http.get("/api/models/catalog", () => HttpResponse.json(geminiCatalog)),
      http.get("/api/settings", () =>
        HttpResponse.json({
          onboarding: { current_step: 4 },
          providers: {},
          knowledge: {},
          agent: {},
        }),
      ),
    ]);

    expect(await screen.findByTestId("gemini-llm-tab")).toBeInTheDocument();
  });

  it("renders a gemini embedding tab when isEmbedding=true and the provider is present", async () => {
    renderCard(true, [
      geminiProvidersHandler(),
      http.get("/api/models/catalog", () => HttpResponse.json(geminiCatalog)),
      http.get("/api/settings", () =>
        HttpResponse.json({
          onboarding: { current_step: 4 },
          providers: {},
          knowledge: {},
          agent: {},
        }),
      ),
    ]);

    expect(
      await screen.findByTestId("gemini-embedding-tab"),
    ).toBeInTheDocument();
  });
});

// ── 2. API key ────────────────────────────────────────────────────────────────

describe("GeminiOnboarding — API key", () => {
  it("shows the API key input when no env key is available", async () => {
    // LabelInput sets data-testid={id}; use that instead of label text because
    // the label contains an icon child that trips exact-text matching.
    renderGemini();
    expect(await screen.findByTestId("gemini-api-key")).toBeInTheDocument();
  });

  it("typing a key stores it in provider_credentials.gemini.api_key", async () => {
    const { user, getSettings } = renderGemini();
    const input = await screen.findByTestId("gemini-api-key");
    await user.type(input, "AIzaTestKey123");
    // The component debounces the key by 500 ms; wait for the effect to fire.
    await waitFor(
      () =>
        expect(getSettings().provider_credentials?.gemini?.api_key).toBe(
          "AIzaTestKey123",
        ),
      { timeout: 1500 },
    );
  });

  it("hides the key input when the env-key toggle is on", async () => {
    renderGemini(false, /* hasEnvApiKey */ true);
    // Toggle is checked by default when hasEnvApiKey is true.
    // The switch has data-testid="gemini-get-from-env-switch".
    const toggle = await screen.findByTestId("gemini-get-from-env-switch");
    expect(toggle).toBeChecked();
    expect(screen.queryByTestId("gemini-api-key")).toBeNull();
  });

  it("shows the key input after turning the env-key toggle off", async () => {
    const { user } = renderGemini(false, /* hasEnvApiKey */ true);
    const toggle = await screen.findByTestId("gemini-get-from-env-switch");
    await user.click(toggle);
    expect(screen.getByTestId("gemini-api-key")).toBeInTheDocument();
  });

  it("disables the toggle when no env key is present", async () => {
    renderGemini(false, /* hasEnvApiKey */ false);
    const toggle = await screen.findByTestId("gemini-get-from-env-switch");
    expect(toggle).toBeDisabled();
  });

  it("sets llm_provider to gemini on mount", async () => {
    const { getSettings } = renderGemini();
    await screen.findByTestId("gemini-api-key");
    expect(getSettings().llm_provider).toBe("gemini");
  });
});

// ── 3. Embedding mode ─────────────────────────────────────────────────────────

describe("GeminiOnboarding — embedding mode", () => {
  it("sets embedding_provider to gemini in embedding mode", async () => {
    const { getSettings } = renderGemini(/* isEmbedding */ true);
    await screen.findByRole("combobox", { name: "Embedding model" });
    expect(getSettings().embedding_provider).toBe("gemini");
  });

  it("updates embedding_model when a catalogue model is selected", async () => {
    const { user, getSettings } = renderGemini(/* isEmbedding */ true);
    const selector = await screen.findByRole("combobox", {
      name: "Embedding model",
    });
    await user.click(selector);
    const option = await screen.findByRole("option", {
      name: "text-embedding-004",
    });
    await user.click(option);
    expect(getSettings().embedding_model).toBe("text-embedding-004");
  });

  it("shows the language model selector in non-embedding mode", async () => {
    renderGemini(/* isEmbedding */ false);
    expect(
      await screen.findByRole("combobox", { name: "Language model" }),
    ).toBeInTheDocument();
  });
});

// ── 4. Badge ──────────────────────────────────────────────────────────────────

describe("OnboardingCard — gemini 'In development' badge", () => {
  it("renders the 'In development' badge when the providers API sends it", async () => {
    renderCard(false, [
      geminiProvidersHandler("In development"),
      http.get("/api/models/catalog", () => HttpResponse.json(geminiCatalog)),
      http.get("/api/settings", () =>
        HttpResponse.json({
          onboarding: { current_step: 4 },
          providers: {},
          knowledge: {},
          agent: {},
        }),
      ),
    ]);

    // Wait for the tab to appear, then assert the badge text is present.
    await screen.findByTestId("gemini-llm-tab");
    expect(screen.getByText("In development")).toBeInTheDocument();
  });
});
