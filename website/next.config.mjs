const configuredBasePath = process.env.PAGES_BASE_PATH ?? "";
const basePath =
  configuredBasePath === "/"
    ? ""
    : configuredBasePath.replace(/\/$/, "");
const [repositoryOwner = "", repositoryName = ""] = (
  process.env.GITHUB_REPOSITORY ?? ""
).split("/");
const githubPagesUrl = repositoryOwner
  ? `https://${repositoryOwner}.github.io/${repositoryName}`
  : "https://www.openr.ag";
const siteUrl = process.env.SITE_URL ?? githubPagesUrl;

/** @type {import('next').NextConfig} */
const nextConfig = {
  // GitHub Pages can only serve static files. `next build` writes the complete
  // site to `out/`, which is the directory published by the Pages workflow.
  output: "export",
  trailingSlash: true,
  basePath,
  assetPrefix: basePath,
  env: {
    NEXT_PUBLIC_BASE_PATH: basePath,
    NEXT_PUBLIC_SITE_URL: siteUrl,
  },
};

export default nextConfig;
