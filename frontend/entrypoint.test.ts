import { spawnSync } from "node:child_process";
import {
  mkdir,
  mkdtemp,
  readdir,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

const entrypoint = resolve(process.cwd(), "entrypoint.sh");
const placeholder = "/NEXT_PUBLIC_BASE_PATH_PLACEHOLDER_a1b2c3d4";
const fixtures: string[] = [];

async function createStandaloneFixture() {
  const directory = await mkdtemp(join(tmpdir(), "openrag-entrypoint-"));
  fixtures.push(directory);
  fixtures.push(`${directory}-runtime`);
  await mkdir(join(directory, ".next/server/app"), { recursive: true });
  await mkdir(join(directory, ".next/static/chunks"), { recursive: true });
  await writeFile(
    join(directory, "server.js"),
    `console.log(JSON.stringify({basePath: "${placeholder}", api: "${placeholder}/api"}));\n`,
  );
  await writeFile(
    join(directory, ".next/server/app/route.js"),
    `server-route: ${placeholder}/api/status\n`,
  );
  await writeFile(
    join(directory, ".next/static/chunks/app.js"),
    `browser-route: ${placeholder}/api/status\n`,
  );
  return directory;
}

function start(directory: string, path?: string) {
  const env = { ...process.env };
  env.OPENRAG_FRONTEND_RUNTIME_DIR = `${directory}-runtime`;
  if (path === undefined) {
    delete env.OPENRAG_FRONTEND_BASE_PATH;
  } else {
    env.OPENRAG_FRONTEND_BASE_PATH = path;
  }
  return spawnSync("sh", [entrypoint, "node", "server.js"], {
    cwd: directory,
    env,
    encoding: "utf8",
  });
}

afterEach(async () => {
  await Promise.all(
    fixtures
      .splice(0)
      .map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

describe("frontend container entrypoint", () => {
  it.each([
    [undefined, ""],
    ["", ""],
    ["/", ""],
    [" openrag-fe/ ", "/openrag-fe"],
    ["/platform/openrag-fe///", "/platform/openrag-fe"],
    ["/r-d_ui", "/r-d_ui"],
  ])("starts the standalone server with %j mounted at %j", async (path, expected) => {
    const directory = await createStandaloneFixture();
    const result = start(directory, path);

    expect(result.error).toBeUndefined();
    expect(result.status, result.stderr).toBe(0);
    expect(result.stdout).toContain(
      JSON.stringify({ basePath: expected, api: `${expected}/api` }),
    );
    expect(
      await readFile(
        join(`${directory}-runtime`, ".next/server/app/route.js"),
        "utf8",
      ),
    ).toBe(`server-route: ${expected}/api/status\n`);
    expect(
      await readFile(
        join(`${directory}-runtime`, ".next/static/chunks/app.js"),
        "utf8",
      ),
    ).toBe(`browser-route: ${expected}/api/status\n`);
    expect(await readFile(join(directory, "server.js"), "utf8")).toContain(
      placeholder,
    );
    expect(await readdir(`${directory}-runtime`)).not.toContain(
      "server.js.bak",
    );
    expect(
      await readdir(join(`${directory}-runtime`, ".next/static/chunks")),
    ).not.toContain("app.js.bak");
  });

  it.each([
    "https://example.com/app",
    "/bad?query",
    "/bad#fragment",
    "//wrong-origin",
    "////",
    "/r&d|ui",
    "/bad\\path",
    "/a//b",
    "/a/../b",
    "/a/./b",
    "/bad path",
    "/bad\npath",
  ])("rejects invalid path %j before touching output", async (path) => {
    const directory = await createStandaloneFixture();
    const result = start(directory, path);

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("OPENRAG_FRONTEND_BASE_PATH");
    expect(result.stdout).not.toContain("basePath");
    expect(await readFile(join(directory, "server.js"), "utf8")).toContain(
      placeholder,
    );
  });

  it("fails clearly when standalone build output is missing", async () => {
    const directory = await mkdtemp(join(tmpdir(), "openrag-entrypoint-"));
    fixtures.push(directory);
    const result = start(directory, "/openrag-fe");

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("Frontend standalone output");
  });
});
