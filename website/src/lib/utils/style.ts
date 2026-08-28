// Types
import { ClassNameHash } from "@/lib/types/definitions";

export function buildClassName(classHash: ClassNameHash): string {
  return Object.keys(classHash)
    .filter((className) => {
      return classHash[className];
    })
    .join(" ");
}

export function textToObject(text = ""): ClassNameHash {
  const arr: Array<string> = text.split(" ");
  const obj: ClassNameHash = {};

  for (let i = 0; i < arr.length; i++) {
    obj[arr[i]] = true;
  }

  return obj;
}
