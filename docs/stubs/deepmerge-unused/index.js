// deepmerge is overridden with this stub in docs/package.json because nothing
// in the docs build imports it (CVE-2026-93753). If a dependency starts to,
// fail loudly so the override gets revisited instead of merging silently.
throw new Error(
  "deepmerge is stubbed out in docs/package.json overrides; a dependency now imports it, so remove the override and re-check CVE-2026-93753."
);
