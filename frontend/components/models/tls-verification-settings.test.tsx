import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  renderWithProviders,
  screen,
  userEvent,
  within,
} from "@/test-utils/render";
import type { CatalogCredentialField } from "./catalog-models";
import { TlsVerificationField } from "./tls-verification-settings";

/** The `ssl_verify` rows the RHOAI and watsonx.ai on-prem catalogues publish. */
const PRESETS = {
  rhoai: {
    key: "ssl_verify",
    label: "Verify TLS certificates",
    placeholder: "/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt",
    tooltip:
      "Path to the CA bundle that signs the endpoint's certificate. In-cluster, this is OpenShift's projected service CA.",
    required: false,
    field_type: "tls_verify",
    default_value: null,
  },
  watsonx: {
    key: "ssl_verify",
    label: "Verify TLS certificates",
    placeholder: "/etc/ssl/certs/openrag-ca.pem",
    tooltip:
      "Optional backend filesystem path to a mounted CA bundle. Include public roots too if this OpenRAG deployment also calls public providers.",
    required: false,
    field_type: "tls_verify",
    default_value: "true",
  },
} satisfies Record<string, CatalogCredentialField>;

/**
 * Renders a field as a parent form would: the value it writes flows back in.
 * `inAccordion` puts it in an open collapsible section, as the forms do.
 */
function renderTls(
  initial: string | undefined,
  preset: keyof typeof PRESETS | CatalogCredentialField,
  {
    savedValue,
    inAccordion = false,
  }: { savedValue?: string; inAccordion?: boolean } = {},
) {
  const field = typeof preset === "string" ? PRESETS[preset] : preset;
  const writes: string[] = [];
  const onWrite = vi.fn((value: string) => writes.push(value));
  function Harness() {
    const [value, setValue] = useState(initial);
    const settings = (
      <TlsVerificationField
        field={field}
        idPrefix="test"
        value={value}
        savedValue={savedValue}
        onValueChange={(next) => {
          onWrite(next);
          setValue(next);
        }}
      />
    );
    if (!inAccordion) return settings;
    return (
      <Accordion type="multiple" defaultValue={["advanced"]}>
        <AccordionItem value="advanced">
          <AccordionTrigger>Advanced settings</AccordionTrigger>
          <AccordionContent>{settings}</AccordionContent>
        </AccordionItem>
      </Accordion>
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

  it.each([
    "/etc/ca.pem",
    "",
    "true",
  ])("restores the saved %j when switched on after its section was collapsed", async (saved) => {
    // Collapsing unmounts the section, so what was switched off from is gone;
    // the saved value is what keeps this from being a target change.
    const { user, writes } = renderTls(saved, preset, {
      savedValue: saved,
      inAccordion: true,
    });
    const section = screen.getByRole("button", { name: "Advanced settings" });

    await user.click(tlsSwitch());
    await user.click(section);
    await user.click(section);
    await user.click(tlsSwitch());

    expect(writes).toEqual(["false", saved]);
  });

  it("forgets a CA path cleared before verification was switched off", async () => {
    const { user, writes } = renderTls("/etc/ca.pem", preset, {
      savedValue: "",
    });

    await user.clear(caPath() as HTMLElement);
    await user.click(tlsSwitch());
    await user.click(tlsSwitch());

    expect(writes.at(-1)).toBe("");
    expect(caPath()).toHaveValue("");
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

  it.each([
    "rhoai",
    "watsonx",
  ] as const)("%s writes the saved value back once a typed CA path is cleared", async (preset) => {
    const { user, writes } = renderTls("", preset, { savedValue: "" });

    await user.type(caPath() as HTMLElement, "/x");
    await user.clear(caPath() as HTMLElement);

    expect(writes.at(-1)).toBe("");
  });

  it.each([
    ["rhoai", ""],
    ["watsonx", "true"],
  ] as const)("%s writes %j when switched on from a saved false", async (preset, expected) => {
    const { user, writes } = renderTls("false", preset, {
      savedValue: "false",
      inAccordion: true,
    });

    await user.click(tlsSwitch());

    expect(writes).toEqual([expected]);
  });
});

describe("TLS verification settings: help text from the catalogue", () => {
  async function tooltipFor(
    user: ReturnType<typeof userEvent.setup>,
    label: string,
  ) {
    const labelElement = screen.getByText(label).closest("label");
    expect(labelElement).not.toBeNull();
    await user.hover(within(labelElement as HTMLElement).getByRole("button"));
    return screen.findByRole("tooltip");
  }

  it.each([
    "rhoai",
    "watsonx",
  ] as const)("%s shows the shared switch description inline", (preset) => {
    renderTls("", preset);

    expect(tlsSwitch()).toHaveAccessibleDescription(
      "Validates the cluster certificate before sending credentials or model traffic.",
    );
  });

  it.each([
    "rhoai",
    "watsonx",
  ] as const)("%s puts the field's tooltip and placeholder on the CA path", async (preset) => {
    const { user } = renderTls("", preset);

    expect(await tooltipFor(user, "Custom CA bundle path")).toHaveTextContent(
      PRESETS[preset].tooltip,
    );
    expect(caPath()).toHaveAttribute(
      "placeholder",
      PRESETS[preset].placeholder,
    );
  });

  it("names the switch with the field's label", () => {
    renderTls("", { ...PRESETS.rhoai, label: "Check certificates" });

    expect(
      screen.getByRole("switch", { name: "Check certificates" }),
    ).toBeChecked();
  });

  it("renders a field with no tooltip or placeholder", () => {
    renderTls("", { ...PRESETS.rhoai, tooltip: null, placeholder: null });

    expect(tlsSwitch()).toBeChecked();
    expect(caPath()).not.toHaveAttribute("placeholder");
    const caLabel = screen.getByText("Custom CA bundle path").closest("label");
    expect(
      within(caLabel as HTMLElement).queryByRole("button"),
    ).not.toBeInTheDocument();
  });
});
