import { describe, expect, it } from "vitest";
import {
  DOCLING_DEFAULT_VLM_LABEL,
  DOCLING_DEFAULT_VLM_PROVIDER,
  DOCLING_DEFAULT_VLM_VALUE,
  doclingDefaultVlmGroup,
  isDoclingDefaultVlm,
  savedVlmSelection,
} from "./docling-default-vlm";

const doclingDefault = {
  model: DOCLING_DEFAULT_VLM_VALUE,
  provider: DOCLING_DEFAULT_VLM_PROVIDER,
};

describe("savedVlmSelection", () => {
  it("is the Docling default when nothing is saved", () => {
    expect(savedVlmSelection(undefined)).toEqual(doclingDefault);
    expect(
      savedVlmSelection({ vlm_model: "", vlm_provider: "openai" }),
    ).toEqual(doclingDefault);
  });

  it("is the Docling default when picture descriptions are on and VLM is off", () => {
    expect(
      savedVlmSelection({
        picture_descriptions: true,
        vlm_enabled: false,
        vlm_model: "gpt-4o",
        vlm_provider: "openai",
      }),
    ).toEqual(doclingDefault);
  });

  it("keeps the saved model while picture descriptions are off", () => {
    expect(
      savedVlmSelection({
        picture_descriptions: false,
        vlm_enabled: false,
        vlm_model: "gpt-4o",
        vlm_provider: "openai",
      }),
    ).toEqual({ model: "gpt-4o", provider: "openai" });
  });

  it("keeps a saved Docling default after picture descriptions are turned off", () => {
    expect(
      savedVlmSelection({
        picture_descriptions: false,
        vlm_enabled: false,
        vlm_model: "gpt-4o",
        vlm_provider: DOCLING_DEFAULT_VLM_PROVIDER,
      }),
    ).toEqual(doclingDefault);
  });

  it("keeps the saved model when VLM is enabled", () => {
    expect(
      savedVlmSelection({
        picture_descriptions: true,
        vlm_enabled: true,
        vlm_model: "gpt-4o",
        vlm_provider: "openai",
      }),
    ).toEqual({ model: "gpt-4o", provider: "openai" });
  });
});

describe("doclingDefaultVlmGroup", () => {
  it("offers a single Docling default option", () => {
    const group = doclingDefaultVlmGroup();
    expect(group.group).toBe("Docling");
    expect(group.provider).toBe(DOCLING_DEFAULT_VLM_PROVIDER);
    expect(group.options).toHaveLength(1);
    expect(group.options[0]).toMatchObject({
      value: DOCLING_DEFAULT_VLM_VALUE,
      label: "Docling default (SmolVLM-256M-Instruct)",
      provider: DOCLING_DEFAULT_VLM_PROVIDER,
    });
    expect(DOCLING_DEFAULT_VLM_LABEL).toBe(
      "Docling default (SmolVLM-256M-Instruct)",
    );
  });
});

describe("isDoclingDefaultVlm", () => {
  it("recognizes only the sentinel value", () => {
    expect(isDoclingDefaultVlm(DOCLING_DEFAULT_VLM_VALUE)).toBe(true);
    expect(isDoclingDefaultVlm("HuggingFaceTB/SmolVLM-256M-Instruct")).toBe(
      false,
    );
    expect(isDoclingDefaultVlm("")).toBe(false);
  });
});
