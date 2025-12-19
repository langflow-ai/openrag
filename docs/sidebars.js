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
        { type: "doc",
          id:  "get-started/install",
          label: "Run the installer script",
        },
        { type: "doc",
          id: "get-started/install-uv",
          label: "Install OpenRAG with uv",
        },
        "get-started/install-uvx",
        { type: "doc",
          id: "get-started/install-windows",
          label: "Install OpenRAG on Windows",
        },
        { type: "doc",
          id: "get-started/docker",
          label: "Deploy self-managed services",
        },
        "get-started/upgrade",
        "get-started/reinstall",
        "get-started/uninstall",
      ],
    },
    "get-started/tui",
    {
      type: "doc",
      id: "get-started/manage-services",
      label: "Manage services",
    },
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
    "support/contribute",
    "support/troubleshoot",
  ],
};

export default sidebars;