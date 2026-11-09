import { describe, expect, it } from "vitest";
import { cn } from "./utils";

describe("cn", () => {
  it("keeps custom font sizes alongside a text color", () => {
    expect(cn("text-mmd", "text-foreground")).toBe("text-mmd text-foreground");
    expect(cn("text-xxs", "text-muted-foreground")).toBe(
      "text-xxs text-muted-foreground",
    );
  });

  it("resolves custom font sizes against other font sizes", () => {
    expect(cn("text-sm", "text-mmd")).toBe("text-mmd");
    expect(cn("text-mmd", "text-xxs")).toBe("text-xxs");
  });

  it("resolves custom radius and spacing against built-in values", () => {
    expect(cn("rounded-md", "rounded-mmd")).toBe("rounded-mmd");
    expect(cn("p-2", "p-mmd")).toBe("p-mmd");
  });
});
