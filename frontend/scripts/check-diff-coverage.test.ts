import { execFileSync, spawnSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

const fixtures = path.resolve("scripts/fixtures/diff-coverage");
const script = path.resolve("scripts/check-diff-coverage.mjs");

describe("diff coverage line accounting", () => {
  it("counts a changed continuation line from its LCOV DA record", () => {
    const repo = mkdtempSync(path.join(tmpdir(), "diff-coverage-"));
    try {
      mkdirSync(path.join(repo, "lib"));
      mkdirSync(path.join(repo, "coverage"));
      execFileSync("git", ["init", "-q"], { cwd: repo });
      writeFileSync(
        path.join(repo, "lib/multiline.ts"),
        readFileSync(path.join(fixtures, "multiline.before.txt")),
      );
      execFileSync("git", ["add", "lib/multiline.ts"], { cwd: repo });
      execFileSync(
        "git",
        [
          "-c",
          "user.name=Diff Coverage Test",
          "-c",
          "user.email=diff-coverage@example.test",
          "commit",
          "-qm",
          "baseline",
        ],
        { cwd: repo },
      );

      writeFileSync(
        path.join(repo, "lib/multiline.ts"),
        readFileSync(path.join(fixtures, "multiline.after.txt")),
      );
      writeFileSync(
        path.join(repo, "coverage/lcov.info"),
        readFileSync(path.join(fixtures, "lcov.info")),
      );

      const result = spawnSync(
        process.execPath,
        [script, "--base", "HEAD", "--threshold", "100"],
        { cwd: repo, encoding: "utf8" },
      );

      expect(result.status).toBe(1);
      expect(result.stdout).toContain("(0/1)");
      expect(result.stdout).toContain("lines: 4");
    } finally {
      rmSync(repo, { recursive: true, force: true });
    }
  });
});
