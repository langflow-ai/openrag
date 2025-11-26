// @ts-check

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

/**
 * Creating a sidebar enables you to:
 - create an ordered group of docs
 - render a sidebar for each doc of that group
 - provide next/previous navigation

 The sidebars can be generated from the filesystem, or explicitly defined here.

 Create as many sidebars as you want.

 @type {import('@docusaurus/plugin-content-docs').SidebarsConfig}
 */
const sidebars = {
  tutorialSidebar: [
    {
      type: "doc",
      id: "get-started/what-is-openrag",
      label: "About OpenRAG"
    },
    "get-started/quickstart",
    "get-started/install",
    "get-started/docker",
    {
      type: "doc",
      id: "core-components/agents",
      label: "Flows",
    },
    {
      type: "category",
      label: "Knowledge",
      items: [
        "core-components/knowledge-configure",
        "core-components/knowledge",
        "core-components/ingestion",
        "core-components/knowledge-filters",
      ],
    },
    {
      type: "doc",
      id: "core-components/chat",
      label: "Chat",
    },
    "reference/configuration",
    "support/troubleshoot",
  ],
};

export default sidebars;