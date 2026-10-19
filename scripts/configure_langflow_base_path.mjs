import fs from "node:fs";

const [file, prefix = ""] = process.argv.slice(2);
if (!file) throw new Error("Usage: node configure_langflow_base_path.mjs <config-constants.ts> [prefix]");
if (prefix !== "" && !/^\/(?:[A-Za-z0-9_~-]+(?:\.[A-Za-z0-9_~-]+)*)(?:\/[A-Za-z0-9_~-]+(?:\.[A-Za-z0-9_~-]+)*)*$/.test(prefix)) {
  throw new Error("LANGFLOW_ROOT_PATH must be empty or an absolute path without trailing slash, empty segments, or dot segments");
}
const values = {
  BASENAME: prefix,
  BASE_URL_API: `${prefix}/api/v1/`,
  BASE_URL_API_V2: `${prefix}/api/v2/`,
  HEALTH_CHECK_URL: `${prefix}/health_check`,
};
let source = fs.readFileSync(file, "utf8");
for (const [name, value] of Object.entries(values)) {
  const pattern = new RegExp(`export const ${name} = [^;]+;`, "g");
  if ([...source.matchAll(pattern)].length !== 1) {
    throw new Error(`Expected exactly one ${name} export in ${file}`);
  }
  source = source.replace(pattern, `export const ${name} = ${JSON.stringify(value)};`);
}
fs.writeFileSync(file, source);
