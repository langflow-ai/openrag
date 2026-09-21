/**
 * OCR language compatibility rules.
 *
 * easyocr loads a single recognition model per job and rejects any language
 * outside it — `lang_list=["ja","ko"]` raises "Japanese is only compatible with
 * English". ocrmac (Apple Vision) has no such constraint, but OpenRAG picks the
 * engine from the host OS, so a selection made on a macOS dev machine has to
 * stay valid in a Linux container. We therefore apply easyocr's stricter rules
 * everywhere.
 *
 * The rule: all selected non-English languages must belong to one family.
 * English is universal and combines with anything.
 */

/** Language that pairs with any other, on every engine. */
const UNIVERSAL = "en";

/**
 * Curated languages grouped by the recognition model that serves them.
 * Mirrors easyocr's model selection (easyocr/easyocr.py) restricted to the
 * languages ocrmac also supports.
 */
export const OCR_LANGUAGE_FAMILIES: Record<string, readonly string[]> = {
  latin: ["fr", "de", "es", "it", "pt", "vi"],
  cyrillic: ["ru", "uk"],
  arabic: ["ar"],
  japanese: ["ja"],
  korean: ["ko"],
  chinese_simplified: ["zh-Hans"],
  chinese_traditional: ["zh-Hant"],
  thai: ["th"],
};

const CURATED = [UNIVERSAL, ...Object.values(OCR_LANGUAGE_FAMILIES).flat()];

/** Keep English as the fallback when another OCR language is selected. */
export function englishLast(languages: string[]): string[] {
  const prioritized = languages.filter((language) => language !== UNIVERSAL);
  if (languages.includes(UNIVERSAL)) prioritized.push(UNIVERSAL);
  return prioritized;
}

function familyOf(language: string): string | undefined {
  return Object.keys(OCR_LANGUAGE_FAMILIES).find((family) =>
    OCR_LANGUAGE_FAMILIES[family].includes(language),
  );
}

/**
 * Families represented in a selection, ignoring English and any raw engine code
 * the picker does not know about. Pass-through codes are deliberately not
 * constrained: an operator typing `hi` knows which engine they are targeting.
 */
function familiesIn(selected: string[]): string[] {
  const families = selected
    .filter((language) => language !== UNIVERSAL)
    .map(familyOf)
    .filter((family): family is string => family !== undefined);
  return [...new Set(families)];
}

/**
 * Languages that may still be chosen given the current selection. Always
 * includes what is already selected, so a selection never renders as invalid
 * against its own options.
 */
export function allowedLanguages(selected: string[]): string[] {
  const families = familiesIn(selected);
  if (families.length === 0) return [...CURATED];

  const allowed = new Set([UNIVERSAL, ...selected]);
  for (const family of families) {
    for (const language of OCR_LANGUAGE_FAMILIES[family]) allowed.add(language);
  }
  return [...allowed];
}

/** True when the selection draws its non-English languages from one family. */
export function isSelectionValid(selected: string[]): boolean {
  return familiesIn(selected).length <= 1;
}
