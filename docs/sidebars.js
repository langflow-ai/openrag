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
    {
      type: "category",
      label: "Installation",
      items: [
        "get-started/install-options",
        "get-started/install",
        "get-started/install-uv-add",
        "get-started/install-uv-pip",
        "get-started/install-uvx",
        "get-started/install-windows",
        "get-started/docker",
        "get-started/upgrade",
        "get-started/reset-reinstall",
        "get-started/uninstall",
      ],
    },
    "get-started/tui",
    "get-started/manage-containers",
    {
      type: "doc",
      id: "core-components/agents",
      label: "Flows",
    },
    {
      type: "category",
      label: "Knowledge",
      items: [
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