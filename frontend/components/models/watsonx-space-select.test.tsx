import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "@/test-utils/render";
import { WatsonxSpaceSelect } from "./watsonx-space-select";

describe("WatsonxSpaceSelect", () => {
  it("lets the user refresh deployment spaces after automatic discovery fails", async () => {
    let attempts = 0;
    const onValueChange = vi.fn();

    renderWithProviders(
      <WatsonxSpaceSelect
        credentials={{
          api_base: "https://cpd.example.com",
          username: "cpd-user",
          api_key: "secret",
          ssl_verify: "true",
        }}
        value=""
        onValueChange={onValueChange}
        idPrefix="test"
      />,
      {
        handlers: [
          http.post("/api/models/watsonx_onprem/spaces", () => {
            attempts += 1;
            if (attempts === 1) {
              return HttpResponse.json(
                { error: "The deployment-space service is unavailable" },
                { status: 503 },
              );
            }
            return HttpResponse.json({
              spaces: [{ id: "space-prod", name: "Production" }],
            });
          }),
        ],
      },
    );

    expect(
      await screen.findByRole("alert", {
        name: "",
      }),
    ).toHaveTextContent("The deployment-space service is unavailable");

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Check the cluster URL, credentials, and that watsonx.ai is available.",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "temporarily turn off Verify TLS certificates",
    );
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Refresh deployment spaces" }),
    );
    await user.click(
      screen.getByRole("combobox", { name: "Deployment space ID" }),
    );
    await user.click(
      await screen.findByRole("option", { name: /Production.*space-prod/ }),
    );

    expect(attempts).toBe(2);
    expect(onValueChange).toHaveBeenCalledWith("space-prod");
  });

  it("does not suggest disabling TLS when verification is already off", async () => {
    renderWithProviders(
      <WatsonxSpaceSelect
        credentials={{
          api_base: "https://cpd.example.com",
          username: "cpd-user",
          api_key: "secret",
          ssl_verify: "false",
        }}
        value=""
        onValueChange={vi.fn()}
        idPrefix="test"
      />,
      {
        handlers: [
          http.post("/api/models/watsonx_onprem/spaces", () =>
            HttpResponse.json(
              { error: "The deployment-space service is unavailable" },
              { status: 503 },
            ),
          ),
        ],
      },
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Check the cluster URL, credentials, and that watsonx.ai is available.",
    );
    expect(alert).not.toHaveTextContent(
      "temporarily turn off Verify TLS certificates",
    );
  });
});
