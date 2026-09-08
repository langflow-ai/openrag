import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  field,
  type ParsedMultipart,
  parseMultipart,
} from "@/test-utils/msw/multipart";
import { server } from "@/test-utils/msw/server";
import {
  duplicateCheck,
  uploadFile,
  uploadFileForContext,
  uploadFiles,
} from "./upload-utils";

/**
 * Chosen by churn: 5 of this file's 15 commits in the last year were bug fixes
 * ("Ingesting folder doesn't seem to work", "fixed onboarding upload to be
 * linked to the task id", "duplicate filter check", plus the CustomEvent →
 * callbacks refactor in #1578 and the context-upload handler in #1624).
 *
 * Everything here goes over real `fetch` with MSW answering, so the request
 * URLs, methods, and FormData bodies are under test alongside the parsing.
 */

const UPLOAD_INGEST = "/api/router/upload_ingest";
const UPLOAD_CONTEXT = "/api/upload_context";
const CHECK_FILENAME = "/api/documents/check-filename";

function txt(name = "a.txt", body = "hello") {
  return new File([body], name, { type: "text/plain" });
}

/**
 * Captures the multipart body of the next POST so tests can assert what was
 * sent. Uses parseMultipart rather than `request.formData()` — see the note in
 * test-utils/msw/multipart.ts for why the latter cannot work under jsdom.
 */
function captureForm(path: string, respond: () => Response) {
  const seen: { form?: ParsedMultipart } = {};
  server.use(
    http.post(path, async ({ request }) => {
      seen.form = parseMultipart(await request.text());
      return respond();
    }),
  );
  return seen;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("uploadFileForContext", () => {
  it("returns a task result for 201 and sends the endpoint", async () => {
    const seen = captureForm(UPLOAD_CONTEXT, () =>
      HttpResponse.json({ task_id: "t-9" }, { status: 201 }),
    );

    const result = await uploadFileForContext(txt(), "/chat", null);

    expect(result).toEqual({ type: "task", taskId: "t-9" });
    expect(field(seen.form!, "endpoint")).toBe("/chat");
    expect(field(seen.form!, "previous_response_id")).toBeUndefined();
  });

  it("forwards previous_response_id only when provided", async () => {
    const seen = captureForm(UPLOAD_CONTEXT, () =>
      HttpResponse.json({ task_id: "t-1" }, { status: 201 }),
    );

    await uploadFileForContext(txt(), "/chat", "resp-7");

    expect(field(seen.form!, "previous_response_id")).toBe("resp-7");
  });

  it("accepts `id` as an alias for task_id on 201", async () => {
    server.use(
      http.post(UPLOAD_CONTEXT, () =>
        HttpResponse.json({ id: "t-alias" }, { status: 201 }),
      ),
    );

    await expect(uploadFileForContext(txt(), "/chat", null)).resolves.toEqual({
      type: "task",
      taskId: "t-alias",
    });
  });

  it("throws when a 201 carries no task id", async () => {
    server.use(
      http.post(UPLOAD_CONTEXT, () => HttpResponse.json({}, { status: 201 })),
    );

    await expect(uploadFileForContext(txt(), "/chat", null)).rejects.toThrow(
      "No task ID received from server",
    );
  });

  it("returns a direct result for 200", async () => {
    server.use(
      http.post(UPLOAD_CONTEXT, () =>
        HttpResponse.json({ filename: "a.txt", response_id: "r-1" }),
      ),
    );

    await expect(uploadFileForContext(txt(), "/chat", null)).resolves.toEqual({
      type: "direct",
      filename: "a.txt",
      responseId: "r-1",
    });
  });

  it("rejects a 200 missing filename or response_id", async () => {
    server.use(
      http.post(UPLOAD_CONTEXT, () => HttpResponse.json({ response_id: "r" })),
    );
    await expect(uploadFileForContext(txt(), "/chat", null)).rejects.toThrow(
      "no filename",
    );

    server.use(
      http.post(UPLOAD_CONTEXT, () => HttpResponse.json({ filename: "a.txt" })),
    );
    await expect(uploadFileForContext(txt(), "/chat", null)).rejects.toThrow(
      "no response_id",
    );
  });

  it("surfaces the server's error body, falling back to a default", async () => {
    server.use(
      http.post(UPLOAD_CONTEXT, () =>
        HttpResponse.text("disk full", { status: 500 }),
      ),
    );
    await expect(uploadFileForContext(txt(), "/chat", null)).rejects.toThrow(
      "disk full",
    );

    server.use(
      http.post(UPLOAD_CONTEXT, () => HttpResponse.text("", { status: 500 })),
    );
    await expect(uploadFileForContext(txt(), "/chat", null)).rejects.toThrow(
      "Failed to process document",
    );
  });
});

describe("duplicateCheck", () => {
  it("encodes the filename into the query string", async () => {
    let url = "";
    server.use(
      http.get(CHECK_FILENAME, ({ request }) => {
        url = request.url;
        return HttpResponse.json({ exists: true });
      }),
    );

    await expect(duplicateCheck(txt("my report&v2.pdf"))).resolves.toEqual({
      exists: true,
    });
    // encodeURIComponent, so a space is %20 (not the form-encoded "+").
    expect(url).toContain("filename=my%20report%26v2.pdf");
  });

  it("throws with the server body when the check fails", async () => {
    server.use(
      http.get(CHECK_FILENAME, () =>
        HttpResponse.text("nope", { status: 500 }),
      ),
    );

    await expect(duplicateCheck(txt())).rejects.toThrow("nope");
  });
});

describe("uploadFiles", () => {
  it("posts every file in one request and returns the task id", async () => {
    const seen = captureForm(UPLOAD_INGEST, () =>
      HttpResponse.json({ task_id: "t-5", file_count: 3 }),
    );

    const result = await uploadFiles([
      txt("a.txt"),
      txt("b.txt"),
      txt("c.txt"),
    ]);

    // Regression: "Ingesting folder doesn't seem to work" — every file must go.
    expect(seen.form?.fileCount).toBe(3);
    expect(result).toEqual({ taskId: "t-5", fileCount: 3, previewMode: false });
  });

  it("defaults fileCount to the number of files sent", async () => {
    server.use(
      http.post(UPLOAD_INGEST, () => HttpResponse.json({ task_id: "t" })),
    );

    const result = await uploadFiles([txt("a.txt"), txt("b.txt")]);

    expect(result.fileCount).toBe(2);
  });

  it("sends replace_duplicates and omits preview unless requested", async () => {
    const seen = captureForm(UPLOAD_INGEST, () =>
      HttpResponse.json({ task_id: "t" }),
    );

    await uploadFiles([txt()], true);

    expect(field(seen.form!, "replace_duplicates")).toBe("true");
    expect(field(seen.form!, "preview")).toBeUndefined();
  });

  it("sends preview and reflects preview_mode back", async () => {
    const seen = captureForm(UPLOAD_INGEST, () =>
      HttpResponse.json({ task_id: "t", preview_mode: true }),
    );

    const result = await uploadFiles([txt()], false, true);

    expect(field(seen.form!, "preview")).toBe("true");
    expect(result.previewMode).toBe(true);
  });

  it("throws the server error message on a failed upload", async () => {
    server.use(
      http.post(UPLOAD_INGEST, () =>
        HttpResponse.json({ error: "too big" }, { status: 413 }),
      ),
    );

    await expect(uploadFiles([txt()])).rejects.toThrow("too big");
  });

  it("throws when the response body is not JSON", async () => {
    server.use(
      http.post(UPLOAD_INGEST, () => HttpResponse.text("<html>502</html>")),
    );

    await expect(uploadFiles([txt()])).rejects.toThrow(
      "unable to parse server response",
    );
  });

  it("throws when a successful response carries no task id", async () => {
    server.use(http.post(UPLOAD_INGEST, () => HttpResponse.json({})));

    await expect(uploadFiles([txt()])).rejects.toThrow("no task ID returned");
  });
});

describe("uploadFile", () => {
  it("reads id and path from the nested upload object", async () => {
    server.use(
      http.post(UPLOAD_INGEST, () =>
        HttpResponse.json({ upload: { id: "f-1", path: "/data/a.txt" } }),
      ),
    );

    const result = await uploadFile(txt());

    expect(result.fileId).toBe("f-1");
    expect(result.filePath).toBe("/data/a.txt");
    expect(result.unified).toBe(true);
  });

  it("falls back through id then task_id for the file id", async () => {
    server.use(
      http.post(UPLOAD_INGEST, () => HttpResponse.json({ id: "f-2" })),
    );
    await expect(uploadFile(txt())).resolves.toMatchObject({ fileId: "f-2" });

    server.use(
      http.post(UPLOAD_INGEST, () => HttpResponse.json({ task_id: "t-3" })),
    );
    // Regression: onboarding upload had to stay linked to the task id.
    await expect(uploadFile(txt())).resolves.toMatchObject({
      fileId: "t-3",
      taskId: "t-3",
    });
  });

  it("defaults filePath to 'uploaded' when the server sends none", async () => {
    server.use(http.post(UPLOAD_INGEST, () => HttpResponse.json({ id: "f" })));

    await expect(uploadFile(txt())).resolves.toMatchObject({
      filePath: "uploaded",
    });
  });

  it("passes create_filter through and echoes the server's decision", async () => {
    const seen = captureForm(UPLOAD_INGEST, () =>
      HttpResponse.json({ id: "f", create_filter: true, filename: "a.txt" }),
    );

    const result = await uploadFile(txt(), false, true);

    expect(field(seen.form!, "create_filter")).toBe("true");
    expect(result.createFilter).toBe(true);
    expect(result.filename).toBe("a.txt");
  });

  it("accepts a COMPLETED or SUCCESS ingestion status", async () => {
    for (const status of ["COMPLETED", "SUCCESS"]) {
      server.use(
        http.post(UPLOAD_INGEST, () =>
          HttpResponse.json({ id: "f", ingestion: { status } }),
        ),
      );
      await expect(uploadFile(txt())).resolves.toMatchObject({ fileId: "f" });
    }
  });

  it("throws when the ingestion pipeline reports another status", async () => {
    server.use(
      http.post(UPLOAD_INGEST, () =>
        HttpResponse.json({
          id: "f",
          ingestion: { status: "FAILED", error: "parser died" },
        }),
      ),
    );

    await expect(uploadFile(txt())).rejects.toThrow(
      /Ingestion failed: parser died/,
    );
  });

  it("ignores an ingestion object with no status field", async () => {
    server.use(
      http.post(UPLOAD_INGEST, () =>
        HttpResponse.json({ id: "f", ingestion: { note: "queued" } }),
      ),
    );

    await expect(uploadFile(txt())).resolves.toMatchObject({ fileId: "f" });
  });

  it("throws when no file id comes back", async () => {
    server.use(http.post(UPLOAD_INGEST, () => HttpResponse.json({})));

    await expect(uploadFile(txt())).rejects.toThrow("no file id returned");
  });

  describe("callbacks (#1578, replacing CustomEvents)", () => {
    it("calls onComplete after a successful upload", async () => {
      server.use(
        http.post(UPLOAD_INGEST, () => HttpResponse.json({ id: "f" })),
      );
      const onComplete = vi.fn();
      const onError = vi.fn();

      await uploadFile(txt(), false, false, { onComplete, onError });

      expect(onComplete).toHaveBeenCalledOnce();
      expect(onError).not.toHaveBeenCalled();
    });

    it("calls onError with the filename and message, then still onComplete", async () => {
      server.use(
        http.post(UPLOAD_INGEST, () =>
          HttpResponse.json({ error: "boom" }, { status: 500 }),
        ),
      );
      const onComplete = vi.fn();
      const onError = vi.fn();

      await expect(
        uploadFile(txt("bad.txt"), false, false, { onComplete, onError }),
      ).rejects.toThrow("boom");

      expect(onError).toHaveBeenCalledWith("bad.txt", "boom");
      // `finally` must still run — the upload UI unblocks on this.
      expect(onComplete).toHaveBeenCalledOnce();
    });

    it("does not let a throwing onError mask the original failure", async () => {
      server.use(
        http.post(UPLOAD_INGEST, () =>
          HttpResponse.json({ error: "original" }, { status: 500 }),
        ),
      );
      vi.spyOn(console, "warn").mockImplementation(() => {});
      const onComplete = vi.fn();

      await expect(
        uploadFile(txt(), false, false, {
          onComplete,
          onError: () => {
            throw new Error("callback exploded");
          },
        }),
      ).rejects.toThrow("original");

      expect(onComplete).toHaveBeenCalledOnce();
    });

    it("does not let a throwing onComplete mask a successful result", async () => {
      server.use(
        http.post(UPLOAD_INGEST, () => HttpResponse.json({ id: "f" })),
      );
      vi.spyOn(console, "warn").mockImplementation(() => {});

      await expect(
        uploadFile(txt(), false, false, {
          onComplete: () => {
            throw new Error("callback exploded");
          },
        }),
      ).resolves.toMatchObject({ fileId: "f" });
    });
  });
});
