import { describe, expect, it } from "vitest";
import {
  allowedLanguages,
  englishLast,
  isSelectionValid,
} from "@/lib/ocr-languages";

describe("englishLast", () => {
  it("moves the default English selection behind a newly chosen language", () => {
    expect(englishLast(["en", "ja"])).toEqual(["ja", "en"]);
  });

  it("preserves the relative priority of other languages", () => {
    expect(englishLast(["en", "ru", "uk"])).toEqual(["ru", "uk", "en"]);
  });

  it("leaves English-only and non-English selections unchanged", () => {
    expect(englishLast(["en"])).toEqual(["en"]);
    expect(englishLast(["ja"])).toEqual(["ja"]);
  });
});

describe("allowedLanguages", () => {
  it("allows every curated language when nothing is selected", () => {
    expect(allowedLanguages([])).toEqual(
      expect.arrayContaining(["en", "ja", "ru", "fr", "ar"]),
    );
  });

  it("allows every curated language when only English is selected", () => {
    // English is universal, so it must never narrow the choices.
    expect(allowedLanguages(["en"])).toEqual(
      expect.arrayContaining(["ja", "ru", "fr", "ar", "th"]),
    );
  });

  it("narrows to English once a restricted language is selected", () => {
    // easyocr loads one recognition model per job: Japanese pairs only with English.
    expect(allowedLanguages(["ja"]).sort()).toEqual(["en", "ja"]);
  });

  it("keeps the rest of the family available for Cyrillic", () => {
    expect(allowedLanguages(["ru"]).sort()).toEqual(["en", "ru", "uk"]);
  });

  it("allows Latin languages to combine freely", () => {
    expect(allowedLanguages(["fr", "de"]).sort()).toEqual([
      "de",
      "en",
      "es",
      "fr",
      "it",
      "pt",
      "vi",
    ]);
  });

  it("does not offer Latin languages alongside Cyrillic", () => {
    expect(allowedLanguages(["uk"])).not.toContain("fr");
  });

  it("treats an unknown pass-through code as unconstrained", () => {
    // Operators may type raw engine codes; the picker must not reason about them.
    expect(allowedLanguages(["hi"])).toEqual(
      expect.arrayContaining(["ja", "fr", "ru"]),
    );
  });
});

describe("isSelectionValid", () => {
  it("accepts a single family plus English", () => {
    expect(isSelectionValid(["en", "ja"])).toBe(true);
    expect(isSelectionValid(["ru", "uk", "en"])).toBe(true);
    expect(isSelectionValid(["fr", "de", "pt"])).toBe(true);
  });

  it("rejects two restricted languages", () => {
    expect(isSelectionValid(["ja", "ko"])).toBe(false);
  });

  it("rejects mixing scripts", () => {
    expect(isSelectionValid(["ru", "fr"])).toBe(false);
  });

  it("accepts English alone", () => {
    expect(isSelectionValid(["en"])).toBe(true);
  });
});
