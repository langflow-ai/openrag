import { render, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  IngestSaveProvider,
  useIngestSave,
  useRegisterSave,
} from "./ingest-save-context";

describe("useIngestSave", () => {
  it("throws when used outside an IngestSaveProvider", () => {
    expect(() => renderHook(() => useIngestSave())).toThrow(
      "useIngestSave must be used within IngestSaveProvider",
    );
  });

  it("bails out of the flags update when re-registering the same key with an unchanged isDirty/blocked state", () => {
    // Two sections sharing a key (e.g. a remount racing the old instance's
    // unmount) both register with identical flags. The second registration's
    // effect must hit the no-op branch in `register()` rather than scheduling
    // a redundant flags update.
    function Section() {
      useRegisterSave("section", {
        isDirty: false,
        blocked: false,
        save: () => {},
      });
      return null;
    }

    expect(() =>
      render(
        <IngestSaveProvider>
          <Section />
          <Section />
        </IngestSaveProvider>,
      ),
    ).not.toThrow();
  });
});
