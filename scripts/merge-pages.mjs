import { constants } from "node:fs";
import { access, cp, mkdir, readdir, readFile, rm } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const [docsBuild, websiteBuild, output] = process.argv.slice(2).map((value) =>
  value ? path.resolve(value) : value,
);

if (!docsBuild || !websiteBuild || !output) {
  console.error(
    "Usage: node scripts/merge-pages.mjs <docs-build> <website-build> <output>",
  );
  process.exit(1);
}

const skippedWebsitePaths = ["404/", "_not-found/"];
const skippedWebsiteFiles = new Set(["404.html"]);
const allowedOverrides = new Set(["index.html"]);

const exists = async (filename) => {
  try {
    await access(filename, constants.F_OK);
    return true;
  } catch {
    return false;
  }
};

const filesMatch = async (left, right) => {
  const [leftContents, rightContents] = await Promise.all([
    readFile(left),
    readFile(right),
  ]);
  return leftContents.equals(rightContents);
};

const copyWebsite = async (directory, relativeDirectory = "") => {
  const entries = await readdir(directory, { withFileTypes: true });

  for (const entry of entries) {
    const relativePath = path.posix.join(relativeDirectory, entry.name);
    const normalizedPath = entry.isDirectory()
      ? `${relativePath}/`
      : relativePath;

    if (
      skippedWebsiteFiles.has(relativePath) ||
      skippedWebsitePaths.some((prefix) => normalizedPath.startsWith(prefix))
    ) {
      continue;
    }

    const source = path.join(directory, entry.name);
    const destination = path.join(output, relativePath);

    if (entry.isDirectory()) {
      await mkdir(destination, { recursive: true });
      await copyWebsite(source, relativePath);
      continue;
    }

    if (
      (await exists(destination)) &&
      !allowedOverrides.has(relativePath) &&
      !(await filesMatch(source, destination))
    ) {
      throw new Error(
        `Refusing to overwrite Docusaurus output with website file: ${relativePath}`,
      );
    }

    await cp(source, destination);
  }
};

await rm(output, { recursive: true, force: true });
await cp(docsBuild, output, { recursive: true });
await copyWebsite(websiteBuild);

for (const requiredFile of [
  "index.html",
  "docs/index.html",
  "quickstart/index.html",
  "404.html",
  ".nojekyll",
]) {
  if (!(await exists(path.join(output, requiredFile)))) {
    throw new Error(`Merged Pages artifact is missing ${requiredFile}`);
  }
}

console.log(`Merged Pages artifact written to ${output}`);
