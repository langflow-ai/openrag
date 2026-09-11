/**
 * Provider badges in the group heading.
 *
 * The badge text comes from `GET /api/models/providers` (`config/model_providers.yaml`
 * on the backend), keyed by provider name — the same list Settings and
 * Onboarding already read. This pins that a provider which declares a badge
 * gets it rendered next to its group heading, and that one which doesn't
 * renders no badge at all.
 */

import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test-utils/msw/server";
import { renderWithProviders, screen } from "@/test-utils/render";
import { ModelSelector } from "./model-selector";
import type { GroupedModelOption } from "./types";

const groupedOptions: GroupedModelOption[] = [
  {
    group: "OpenShift AI Models",
    provider: "rhoai",
    options: [{ value: "granite-3.1-8b-instruct", label: "Granite 3.1 8B" }],
  },
];

function setup() {
  return renderWithProviders(
    <ModelSelector
      groupedOptions={groupedOptions}
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

    setup();

    expect(await screen.findByText("Tech Preview")).toBeInTheDocument();
  });

  it("renders no badge when the provider declares none", async () => {
    mockProviders([{ name: "rhoai", display_name: "Red Hat OpenShift AI" }]);

    setup();

    // Wait for the providers response to land, then confirm nothing appeared.
    await screen.findByText("OpenShift AI Models");
    expect(screen.queryByText("Tech Preview")).not.toBeInTheDocument();
  });
});
