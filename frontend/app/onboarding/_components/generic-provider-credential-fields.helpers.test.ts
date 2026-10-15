import { describe, expect, it } from "vitest";
import { clearedSavedCredentialKeys } from "./generic-provider-credential-fields.helpers";

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
