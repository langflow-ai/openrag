import { describe, expect, it } from "vitest";
import {
  activeCredentialKeys,
  authMethodCredentialKeys,
  clearedSavedCredentialKeys,
  credentialTargetChanged,
  groupRhoaiFields,
  rhoaiAdvancedOpenByDefault,
  secretsToReenter,
} from "./provider-credentials";

describe("authMethodCredentialKeys", () => {
  it.each([
    ["watsonx_onprem", "username_api_key", ["username", "api_key"]],
    ["watsonx_onprem", "zen_api_key", ["zen_api_key"]],
    // Anything else is the method the form offers first.
    ["watsonx_onprem", "unknown", ["username", "api_key"]],
  ])("lists every key of %s's %s method", (provider, method, expected) => {
    expect(authMethodCredentialKeys(provider, "api_key", method)).toEqual(
      expected,
    );
  });

  it.each([
    ["api_key", ["api_key"]],
    ["service_principal", ["tenant_id", "client_id", "client_secret"]],
    ["unknown", []],
  ])("lists every key of Azure's %s method", (method, expected) => {
    expect(
      authMethodCredentialKeys("azure", method, "username_api_key"),
    ).toEqual(expected);
  });

  it("is empty for a provider with no auth-method choice", () => {
    expect(
      authMethodCredentialKeys("rhoai", "api_key", "username_api_key"),
    ).toEqual([]);
  });
});

describe("activeCredentialKeys", () => {
  it("adds the chosen on-prem method's keys to the shared fields", () => {
    expect(
      activeCredentialKeys("watsonx_onprem", "api_key", "zen_api_key"),
    ).toEqual(
      new Set([
        "api_base",
        "space_id",
        "project_id",
        "ssl_verify",
        "zen_api_key",
      ]),
    );
  });

  it("adds the chosen Azure method's keys to the endpoint fields", () => {
    expect(
      activeCredentialKeys("azure", "entra_token", "username_api_key"),
    ).toEqual(new Set(["api_base", "api_version", "azure_ad_token"]));
  });

  it("is null for a provider with no auth-method choice", () => {
    expect(
      activeCredentialKeys("rhoai", "api_key", "username_api_key"),
    ).toBeNull();
  });
});

describe("clearedSavedCredentialKeys", () => {
  const saved = {
    api_base: "https://chat.example.com/v1",
    embedding_api_base: "https://embed.example.com/v1",
    ssl_verify: "/etc/pki/ca.crt",
  };

  it("lists saved non-secret fields the operator emptied", () => {
    expect(
      clearedSavedCredentialKeys(
        {
          api_base: "https://chat.example.com/v1",
          embedding_api_base: "  ",
          ssl_verify: "",
        },
        saved,
        new Set(),
        null,
      ),
    ).toEqual(["embedding_api_base", "ssl_verify"]);
  });

  it("leaves out a blank secret, which keeps the saved one", () => {
    expect(
      clearedSavedCredentialKeys(
        { api_key: "" },
        { ...saved, api_key: "redacted" },
        new Set(["api_key"]),
        null,
      ),
    ).toEqual([]);
  });

  it("leaves out a blank field that was never saved", () => {
    expect(
      clearedSavedCredentialKeys({ project_id: "" }, saved, new Set(), null),
    ).toEqual([]);
  });

  it("leaves out fields the chosen auth method does not use", () => {
    expect(
      clearedSavedCredentialKeys(
        { username: "", api_base: "" },
        { username: "cpd-user", api_base: "https://cpd.example.com" },
        new Set(),
        new Set(["api_base", "zen_api_key"]),
      ),
    ).toEqual(["api_base"]);
  });
});

describe("credentialTargetChanged", () => {
  const saved = {
    api_base: "https://chat.example.com/v1",
    ssl_verify: "true",
    username: "cpd-user",
  };

  it("is false while every target field matches what was saved", () => {
    expect(
      credentialTargetChanged(
        { api_base: " https://chat.example.com/v1 ", ssl_verify: "true" },
        saved,
      ),
    ).toBe(false);
  });

  it("ignores fields that are not targets", () => {
    expect(
      credentialTargetChanged(
        { ...saved, username: "someone-else", api_key: "typed" },
        saved,
      ),
    ).toBe(false);
  });

  it.each([
    ["a new endpoint", { ...saved, api_base: "https://other.example.com/v1" }],
    ["a new TLS setting", { ...saved, ssl_verify: "false" }],
    ["a cleared endpoint", { ...saved, api_base: "" }],
    [
      "a newly set embedding endpoint",
      { ...saved, embedding_api_base: "https://embed.example.com/v1" },
    ],
  ])("is true for %s", (_name, credentials) => {
    expect(credentialTargetChanged(credentials, saved)).toBe(true);
  });
});

describe("secretsToReenter", () => {
  const savedSecrets = new Set(["api_key", "zen_api_key"]);

  it("lists nothing while the target is unchanged", () => {
    expect(secretsToReenter({}, savedSecrets, null, false)).toEqual([]);
  });

  it("lists every blank saved secret once the target changed", () => {
    expect(
      secretsToReenter({ api_key: "  " }, savedSecrets, null, true),
    ).toEqual(["api_key", "zen_api_key"]);
  });

  it("leaves out a secret that was typed again", () => {
    expect(
      secretsToReenter({ api_key: "new" }, savedSecrets, null, true),
    ).toEqual(["zen_api_key"]);
  });

  it("leaves out secrets the chosen auth method does not use", () => {
    expect(
      secretsToReenter(
        {},
        savedSecrets,
        new Set(["api_base", "username", "api_key"]),
        true,
      ),
    ).toEqual(["api_key"]);
  });
});

describe("groupRhoaiFields", () => {
  const field = (key: string) => ({
    key,
    label: key,
    required: false,
    field_type: "text",
  });
  const keys = (fields: Array<{ key: string }>) => fields.map((f) => f.key);

  it("puts the endpoints and token up front and the tuning behind Advanced", () => {
    // Catalogue order deliberately differs from the display order.
    const grouped = groupRhoaiFields([
      field("ssl_verify"),
      field("api_key"),
      field("embedding_max_concurrency"),
      field("embedding_api_base"),
      field("api_base"),
    ]);

    expect(keys(grouped.primary)).toEqual([
      "api_base",
      "embedding_api_base",
      "api_key",
    ]);
    expect(keys(grouped.advanced)).toEqual([
      "embedding_max_concurrency",
      "ssl_verify",
    ]);
  });

  it("shows a field neither group names up front instead of dropping it", () => {
    const grouped = groupRhoaiFields([
      field("api_base"),
      field("new_backend_field"),
      field("ssl_verify"),
    ]);

    expect(keys(grouped.primary)).toEqual(["api_base", "new_backend_field"]);
    expect(keys(grouped.advanced)).toEqual(["ssl_verify"]);
  });

  it("skips fields the catalogue does not publish", () => {
    expect(groupRhoaiFields([field("api_base")])).toEqual({
      primary: [field("api_base")],
      advanced: [],
    });
    expect(groupRhoaiFields([])).toEqual({ primary: [], advanced: [] });
  });
});

describe("rhoaiAdvancedOpenByDefault", () => {
  it.each([
    [undefined, false],
    [{}, false],
    [{ api_base: "https://chat.example.com/v1" }, false],
    [{ ssl_verify: "" }, false],
    [{ ssl_verify: "true" }, false],
    [{ embedding_max_concurrency: "  " }, false],
    [{ ssl_verify: "false" }, true],
    [{ ssl_verify: "/var/run/secrets/ca.crt" }, true],
    [{ embedding_max_concurrency: "4" }, true],
  ])("opens for %j → %s", (saved, expected) => {
    expect(rhoaiAdvancedOpenByDefault(saved)).toBe(expected);
  });
});
