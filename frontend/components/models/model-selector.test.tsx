import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test-utils/msw/server";
import { renderWithProviders, screen, userEvent } from "@/test-utils/render";
import { ModelSelector } from "./model-selector";
import type { GroupedModelOption } from "./types";

describe("ModelSelector custom entries", () => {
  it("offers a typed model under every configured provider group", async () => {
    const onValueChange = vi.fn();
    const user = userEvent.setup();

    renderWithProviders(
      <ModelSelector
        groupedOptions={[
          {
            group: "OpenAI",
            provider: "openai",
            options: [{ value: "gpt-4o", label: "gpt-4o" }],
          },
          {
            group: "Anthropic",
            provider: "anthropic",
            options: [{ value: "claude-sonnet-4", label: "Claude Sonnet 4" }],
          },
        ]}
        custom
        value=""
        onValueChange={onValueChange}
        defaultOpen
      />,
    );

    await user.type(
      screen.getByTestId("model-search-input"),
      "acme/private-model",
    );

    expect(
      screen.getByRole("option", {
        name: "Use openai:acme/private-model",
      }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("option", {
        name: "Use anthropic:acme/private-model",
      }),
    );

    expect(onValueChange).toHaveBeenCalledWith(
      "acme/private-model",
      "anthropic",
    );
  });
});

describe("ModelSelector flat previews", () => {
  const azureModels = [
    ...Array.from({ length: 44 }, (_, index) => ({
      value: `gpt-5-${String(index).padStart(2, "0")}`,
      label: `gpt-5-${String(index).padStart(2, "0")}`,
    })),
    { value: "gpt-4.1", label: "gpt-4.1" },
  ];

  it("offers an explicit Show all action for onboarding models beyond the preview", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ModelSelector
        options={azureModels}
        previewLimit={5}
        value=""
        onValueChange={vi.fn()}
        defaultOpen
      />,
    );

    expect(screen.queryByRole("option", { name: "gpt-4.1" })).toBeNull();
    await user.click(
      screen.getByRole("option", { name: "Show all 45 models" }),
    );
    expect(screen.getByRole("option", { name: "gpt-4.1" })).toBeInTheDocument();
  });

  it("searches models beyond the preview without expanding first", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ModelSelector
        options={azureModels}
        previewLimit={5}
        value=""
        onValueChange={vi.fn()}
        defaultOpen
      />,
    );

    await user.type(screen.getByTestId("model-search-input"), "gpt-4.1");
    expect(screen.getByRole("option", { name: "gpt-4.1" })).toBeInTheDocument();
  });
});

/**
 * Provider badges in the group heading.
 *
 * The badge text comes from `GET /api/models/providers` (`config/model_providers.yaml`
 * on the backend), keyed by provider name — the same list Settings and
 * Onboarding already read. This pins that a provider which declares a badge
 * gets it rendered next to its group heading, and that one which doesn't
 * renders no badge at all.
 */

const badgeGroupedOptions: GroupedModelOption[] = [
  {
    group: "OpenShift AI Models",
    provider: "rhoai",
    options: [{ value: "granite-3.1-8b-instruct", label: "Granite 3.1 8B" }],
  },
];

function setupBadges() {
  return renderWithProviders(
    <ModelSelector
      groupedOptions={badgeGroupedOptions}
      value=""
      onValueChange={vi.fn()}
      defaultOpen
    />,
  );
}

function mockProviders(
  providers: Array<{ name: string; display_name: string; badge?: string }>,
) {
  server.use(
    http.get("/api/models/providers", () =>
      HttpResponse.json({ run_mode: "oss", providers }),
    ),
  );
}

describe("ModelSelector provider badges", () => {
  it("shows the badge the providers API sent for the group's provider", async () => {
    mockProviders([
      {
        name: "rhoai",
        display_name: "Red Hat OpenShift AI",
        badge: "Tech Preview",
      },
    ]);

    setupBadges();

    expect(await screen.findByText("Tech Preview")).toBeInTheDocument();
  });

  it("renders no badge when the provider declares none", async () => {
    mockProviders([{ name: "rhoai", display_name: "Red Hat OpenShift AI" }]);

    setupBadges();

    // Wait for the providers response to land, then confirm nothing appeared.
    await screen.findByText("OpenShift AI Models");
    expect(screen.queryByText("Tech Preview")).not.toBeInTheDocument();
  });
});
