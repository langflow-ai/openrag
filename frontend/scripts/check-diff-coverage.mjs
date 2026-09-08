#!/usr/bin/env node
/**
 * Diff coverage gate.
 *
 * Fails when lines ADDED OR CHANGED by this branch are not covered by the
 * Vitest suite. Deliberately scoped to changed lines rather than whole changed
 * files: gating on file coverage would fail a one-line fix to an untested
 * legacy file, which teaches people to avoid touching legacy code. Gating on
 * changed lines says only "test what you just wrote".
 *
 * Usage:
 *   node scripts/check-diff-coverage.mjs [--base <ref>] [--threshold <0-100>]
 *
 * Env:
 *   DIFF_COVERAGE_BASE       base ref (default: origin/main)
 *   DIFF_COVERAGE_THRESHOLD  minimum percent (default: 80)
 *
 * Requires `vitest run --coverage` to have produced coverage/coverage-final.json.
 */
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

const args = process.argv.slice(2);
function arg(name, fallback) {
  const i = args.indexOf(`--${name}`);
  return i !== -1 && args[i + 1] ? args[i + 1] : fallback;
}

const BASE = arg("base", process.env.DIFF_COVERAGE_BASE || "origin/main");
const THRESHOLD = Number(
  arg("threshold", process.env.DIFF_COVERAGE_THRESHOLD || "80"),
);
const COVERAGE_FILE = path.resolve("coverage/coverage-final.json");

/** Source files we gate on. Mirrors coverage.include in vitest.config.mts. */
const INCLUDED =
  /^(app|components|contexts|hooks|lib|enhancements)\/.*\.(ts|tsx)$/;
/** Never gate on these: tests themselves, types, and Next route plumbing. */
const EXCLUDED =
  /(\.test\.tsx?$|\.d\.ts$|\/(layout|error|global-error|loading)\.tsx$|\/route\.ts$)/;

function git(...a) {
  return execFileSync("git", a, {
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
}

/** Resolves the merge base, so we only judge lines this branch introduced. */
function mergeBase(base) {
  try {
    return git("merge-base", base, "HEAD").trim();
  } catch {
    console.error(
      `diff-coverage: cannot resolve base ref "${base}".\n` +
        "In CI, check out with fetch-depth: 0 so history is available.",
    );
    process.exit(2);
  }
}

/**
 * Returns Map<file, Set<lineNumber>> of lines added or modified vs the base.
 * `-U0` keeps hunks tight so we never attribute untouched context lines.
 *
 * Diffs the merge base against the WORKING TREE, not against HEAD. In CI the
 * two are identical, but locally this makes the gate cover uncommitted work —
 * which is when a developer actually wants the answer.
 */
function changedLines(baseSha) {
  const out = git("diff", "-U0", "--diff-filter=d", "--relative", baseSha);
  const files = new Map();
  let file = null;
  let line = 0;

  for (const raw of out.split("\n")) {
    if (raw.startsWith("+++ ")) {
      const p = raw.slice(4).trim();
      file = p === "/dev/null" ? null : p.replace(/^b\//, "");
      continue;
    }
    if (raw.startsWith("@@")) {
      // @@ -old,count +new,count @@
      const m = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/.exec(raw);
      if (m) line = Number(m[1]);
      continue;
    }
    if (!file) continue;
    if (raw.startsWith("+")) {
      if (!files.has(file)) files.set(file, new Set());
      files.get(file).add(line);
      line++;
    }
    // '-' lines do not advance the new-file counter; with -U0 there is no context.
  }
  return files;
}

/** Maps absolute coverage paths to Map<relPath, Map<line, hitCount>>. */
function lineHitsByFile() {
  if (!existsSync(COVERAGE_FILE)) {
    console.error(
      `diff-coverage: ${path.relative(process.cwd(), COVERAGE_FILE)} not found.\n` +
        "Run `npm run test:coverage` first.",
    );
    process.exit(2);
  }
  const raw = JSON.parse(readFileSync(COVERAGE_FILE, "utf8"));
  const byFile = new Map();

  for (const entry of Object.values(raw)) {
    const rel = path.relative(process.cwd(), entry.path);
    const hits = new Map();
    for (const [id, loc] of Object.entries(entry.statementMap ?? {})) {
      const count = entry.s?.[id] ?? 0;
      const ln = loc?.start?.line;
      if (!ln) continue;
      // A line counts as covered if any statement starting on it ran.
      hits.set(ln, Math.max(hits.get(ln) ?? 0, count));
    }
    byFile.set(rel, hits);
  }
  return byFile;
}

const baseSha = mergeBase(BASE);
const changed = changedLines(baseSha);
const coverage = lineHitsByFile();

let totalRelevant = 0;
let totalCovered = 0;
const offenders = [];

for (const [file, lines] of changed) {
  if (!INCLUDED.test(file) || EXCLUDED.test(file)) continue;

  const hits = coverage.get(file);
  // A changed source file absent from the coverage report has no executed
  // statements at all — every changed executable line is uncovered. We cannot
  // know which lines are executable, so treat the file as fully uncovered only
  // if it is a real source file; report it explicitly rather than silently.
  if (!hits) {
    offenders.push({ file, relevant: lines.size, covered: 0, unknown: true });
    totalRelevant += lines.size;
    continue;
  }

  let relevant = 0;
  let covered = 0;
  const missed = [];
  for (const ln of lines) {
    if (!hits.has(ln)) continue; // not an executable statement (blank, comment, type)
    relevant++;
    if (hits.get(ln) > 0) covered++;
    else missed.push(ln);
  }
  totalRelevant += relevant;
  totalCovered += covered;
  if (missed.length) offenders.push({ file, relevant, covered, missed });
}

if (totalRelevant === 0) {
  console.log("diff-coverage: no changed executable lines to check — passing.");
  process.exit(0);
}

const pct = (100 * totalCovered) / totalRelevant;
const verdict = pct >= THRESHOLD ? "PASS" : "FAIL";

console.log(
  `diff-coverage: ${pct.toFixed(1)}% of changed lines covered ` +
    `(${totalCovered}/${totalRelevant}), threshold ${THRESHOLD}% — ${verdict}`,
);

if (offenders.length) {
  console.log("\nUncovered changed lines:");
  for (const o of offenders.sort((a, b) => a.file.localeCompare(b.file))) {
    if (o.unknown) {
      console.log(
        `  ${o.file} — no coverage data (file never imported by a test)`,
      );
      continue;
    }
    console.log(`  ${o.file} — ${o.covered}/${o.relevant} covered`);
    console.log(`    lines: ${formatRanges(o.missed)}`);
  }
}

/** Collapses [3,4,5,9] into "3-5, 9" so long lists stay readable. */
function formatRanges(nums) {
  const s = [...nums].sort((a, b) => a - b);
  const parts = [];
  let start = s[0];
  let prev = s[0];
  for (let i = 1; i <= s.length; i++) {
    if (s[i] === prev + 1) {
      prev = s[i];
      continue;
    }
    parts.push(start === prev ? `${start}` : `${start}-${prev}`);
    start = s[i];
    prev = s[i];
  }
  return parts.join(", ");
}

process.exit(pct >= THRESHOLD ? 0 : 1);
