import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import {
  formatBytes,
  isImportBusy,
  SnapshotApiError,
  type SnapshotImport,
  snapshotRequest,
} from "./opensearch-snapshot";

const imp = (
  status: SnapshotImport["status"],
  state: SnapshotImport["job"]["state"],
) => ({ status, job: { state } }) as SnapshotImport;

describe("formatBytes", () => {
  it("formats sizes and hides unknown ones", () => {
    expect(formatBytes(0)).toBe("—");
    expect(formatBytes(undefined)).toBe("—");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(20 * 1024 * 1024)).toBe("20 MB");
  });
});

describe("isImportBusy", () => {
  it("is busy while staging, restoring, deleting or running a job", () => {
    expect(isImportBusy(imp("staging", "running"))).toBe(true);
    expect(isImportBusy(imp("restoring", "queued"))).toBe(true);
    expect(isImportBusy(imp("deleting", "idle"))).toBe(true);
    expect(isImportBusy(imp("active", "running"))).toBe(true);
  });

  it("is settled in review, active, or failed with an idle/failed job", () => {
    expect(isImportBusy(imp("review", "idle"))).toBe(false);
    expect(isImportBusy(imp("active", "idle"))).toBe(false);
    expect(isImportBusy(imp("failed", "failed"))).toBe(false);
    expect(isImportBusy(imp("staging", "failed"))).toBe(false);
    expect(isImportBusy(imp("deleting", "failed"))).toBe(false);
    expect(isImportBusy(imp("deleting", "cancelled"))).toBe(false);
  });
});

async function rejection(path: string): Promise<SnapshotApiError> {
  try {
    await snapshotRequest(path, { fallbackError: "fallback" });
  } catch (error) {
    return error as SnapshotApiError;
  }
  throw new Error("expected the request to be rejected");
}

describe("snapshotRequest errors", () => {
  const fail = async (status: number, body: object) => {
    server.use(
      http.get("/api/connectors/opensearch_snapshot/x", () =>
        HttpResponse.json(body, { status }),
      ),
    );
    return rejection("/x");
  };

  it("reads error and code from a flat body", async () => {
    const error = await fail(400, { error: "bad endpoint", code: "blocked" });
    expect(error).toBeInstanceOf(SnapshotApiError);
    expect(error).toMatchObject({
      status: 400,
      message: "bad endpoint",
      code: "blocked",
    });
  });

  it("reads a FastAPI detail object, including blockers and role JSON", async () => {
    const blockers = [{ code: "too_large", message: "Too large" }];
    const error = await fail(409, {
      detail: {
        error: "nope",
        code: "role_not_provisioned",
        blockers,
        role_json: { role: "r" },
      },
    });
    expect(error.code).toBe("role_not_provisioned");
    expect(error.blockers).toEqual(blockers);
    expect(error.roleJson).toEqual({ role: "r" });
  });

  it("reads a plain string detail and validation detail lists", async () => {
    expect((await fail(404, { detail: "Not found" })).message).toBe(
      "Not found",
    );
    expect(
      (await fail(422, { detail: [{ msg: "field required" }, { msg: "bad" }] }))
        .message,
    ).toBe("field required; bad");
  });

  it("falls back when the body is empty or not JSON", async () => {
    server.use(
      http.get("/api/connectors/opensearch_snapshot/y", () =>
        HttpResponse.text("boom", { status: 502 }),
      ),
    );
    const error = await rejection("/y");
    expect(error).toMatchObject({
      status: 502,
      message: "fallback",
      code: null,
    });
  });
});
