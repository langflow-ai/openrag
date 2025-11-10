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
    {
      type: "doc",
      id: "get-started/quickstart",
      label: "Quickstart"
    },
    {
      type: "doc",
      id: "get-started/install",
      label: "Install OpenRAG with TUI"
    },
    {
      type: "doc",
      id: "get-started/docker",
      label: "Install OpenRAG containers"
    },
    {
      type: "doc",
      id: "core-components/agents",
      label: "Langflow in OpenRAG"
    },
    {
      type: "doc",
      id: "core-components/knowledge",
      label: "OpenSearch in OpenRAG"
    },
    {
      type: "doc",
      id: "core-components/ingestion",
      label: "Docling in OpenRAG"
    },
    {
      type: "doc",
      id: "reference/configuration",
      label: "Environment variables"
    },
    {
      type: "doc",
      id: "support/troubleshoot",
      label: "Troubleshooting"
    },
  ],
};

export default sidebars;