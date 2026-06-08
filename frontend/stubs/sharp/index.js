// No-op stub for `sharp`. Next.js lists sharp as an optional dependency for its
// built-in image optimizer. Image optimization is disabled (images.unoptimized
// in next.config.ts), so sharp is never invoked at runtime. This stub is mapped
// in via the "sharp" override in package.json to avoid pulling the LGPL-3.0
// libvips native binaries into the lockfile.
module.exports = {};
