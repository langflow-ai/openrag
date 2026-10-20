import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  renderWithProviders,
  screen,
  userEvent,
  within,
} from "@/test-utils/render";
import {
  RhoaiTlsSettings,
  WatsonxTlsSettings,
} from "./tls-verification-settings";

const PRESETS = {
  rhoai: RhoaiTlsSettings,
  watsonx: WatsonxTlsSettings,
} as const;

/** Renders a preset as a parent form would: the value it writes flows back in. */
function renderTls(initial: string | undefined, preset: keyof typeof PRESETS) {
  const Preset = PRESETS[preset];
  const writes: string[] = [];
  const onWrite = vi.fn((value: string) => writes.push(value));
  function Harness() {
    const [value, setValue] = useState(initial);
    return (
      <Preset
        idPrefix="test"
        value={value}
        onValueChange={(next) => {
          onWrite(next);
          setValue(next);
        }}
      />
    );
  }
  renderWithProviders(<Harness />, { providers: ["tooltip"] });
  return { user: userEvent.setup(), writes, onWrite };
}

const tlsSwitch = () =>
  screen.getByRole("switch", { name: "Verify TLS certificates" });
const caPath = () =>
  screen.queryByRole("textbox", { name: "Custom CA bundle path" });

describe.each([
  "rhoai",
  "watsonx",
] as const)("%s TLS verification settings", (preset) => {
  it("verifies by default when nothing is stored", () => {
    renderTls(undefined, preset);

    expect(tlsSwitch()).toBeChecked();
    expect(caPath()).toHaveValue("");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("stores false when switched off and warns instead of asking for a CA", async () => {
    const { user, writes } = renderTls("", preset);

    await user.click(tlsSwitch());

    expect(writes.at(-1)).toBe("false");
    expect(tlsSwitch()).not.toBeChecked();
    expect(caPath()).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Certificate verification is disabled.",
    );
  });

  it("restores the CA path typed before verification was switched off", async () => {
    const { user, writes } = renderTls("", preset);

    await user.type(caPath() as HTMLElement, "/etc/ca.pem");
    expect(writes.at(-1)).toBe("/etc/ca.pem");
    await user.click(tlsSwitch());
    await user.click(tlsSwitch());

    expect(writes.at(-1)).toBe("/etc/ca.pem");
    expect(caPath()).toHaveValue("/etc/ca.pem");
  });

  it("shows a stored CA path in the CA box", () => {
    renderTls("/var/run/secrets/ca.crt", preset);
    expect(tlsSwitch()).toBeChecked();
    expect(caPath()).toHaveValue("/var/run/secrets/ca.crt");
  });

  it.each([
    "false",
    "OFF",
    "0",
  ])("shows a stored %j as switched off", (stored) => {
    renderTls(stored, preset);
    expect(tlsSwitch()).not.toBeChecked();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it.each([
    "",
    "true",
  ])("writes the stored %j back when switched off and on again", async (stored) => {
    // Anything else would count as a new credential target and make the
    // operator retype a saved token for an unchanged setting.
    const { user, writes } = renderTls(stored, preset);

    await user.click(tlsSwitch());
    await user.click(tlsSwitch());

    expect(writes).toEqual(["false", stored]);
  });
});

describe("TLS verification settings: the verified value", () => {
  it.each([
    ["rhoai", ""],
    ["watsonx", "true"],
  ] as const)("%s writes %j when switched on from a stored false with no CA path", async (preset, expected) => {
    const { user, writes } = renderTls("false", preset);

    await user.click(tlsSwitch());

    expect(writes).toEqual([expected]);
    expect(caPath()).toHaveValue("");
  });

  it.each([
    ["rhoai", ""],
    ["watsonx", "true"],
  ] as const)("%s writes %j once a stored CA path is cleared", async (preset, expected) => {
    const { user, writes } = renderTls("/etc/ca.pem", preset);

    await user.clear(caPath() as HTMLElement);

    expect(writes.at(-1)).toBe(expected);
    expect(tlsSwitch()).toBeChecked();
  });
});

describe("TLS verification settings: help text", () => {
  async function tooltipFor(
    user: ReturnType<typeof userEvent.setup>,
    label: string,
  ) {
    const labelElement = screen.getByText(label).closest("label");
    expect(labelElement).not.toBeNull();
    await user.hover(within(labelElement as HTMLElement).getByRole("button"));
    return screen.findByRole("tooltip");
  }

  it("shows the RHOAI switch help as an inline description", () => {
    renderTls("", "rhoai");

    expect(tlsSwitch()).toHaveAccessibleDescription(
      "Validates the cluster certificate before sending credentials or model traffic.",
    );
  });

  it("puts the RHOAI CA path help behind an info icon", async () => {
    const { user } = renderTls("", "rhoai");

    expect(await tooltipFor(user, "Custom CA bundle path")).toHaveTextContent(
      "Path to the CA bundle that signs the endpoint's certificate. In-cluster this is OpenShift's projected service CA.",
    );
    expect(caPath()).toHaveAttribute(
      "placeholder",
      "/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt",
    );
  });

  it("keeps the watsonx switch help as an inline description", () => {
    renderTls("true", "watsonx");

    expect(tlsSwitch()).toHaveAccessibleDescription(
      "Recommended. Validates the cluster certificate before sending credentials or model traffic.",
    );
    expect(caPath()).toHaveAttribute(
      "placeholder",
      "/etc/ssl/certs/openrag-ca.pem",
    );
  });
});
