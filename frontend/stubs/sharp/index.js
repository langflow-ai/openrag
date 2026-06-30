/* ******************************************************************************
 * IBM Confidential
 *
 * OCO Source Materials
 *
 *  Copyright IBM Corp. 2026  All Rights Reserved.
 *
 * The source code for this program is not published or otherwise divested
 * of its trade secrets, irrespective of what has been deposited with
 * the U.S. Copyright Office.
 ****************************************************************************** */

// No-op stub for `sharp`. Next.js lists sharp as an optional dependency for its
// built-in image optimizer. Image optimization is disabled (images.unoptimized
// in next.config.ts), so sharp is never invoked at runtime. This stub is mapped
// in via the "sharp" override in package.json to avoid pulling the LGPL-3.0
// libvips native binaries into the lockfile.
module.exports = {};
