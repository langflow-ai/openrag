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

import type { KnipConfig } from "knip";

const config: KnipConfig = {
  entry: ["app/**/*.{ts,tsx}", "next.config.ts"],
  project: ["**/*.{ts,tsx}"],
  ignore: ["**/*.d.ts", "**/node_modules/**", ".next/**", "public/**"],
};

export default config;
