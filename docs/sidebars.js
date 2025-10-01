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
      type: "category",
      label: "Get Started",
      items: [
        {
          type: "doc",
          id: "get-started/what-is-openrag",
          label: "About OpenRAG"
        },
        {
          type: "doc",
          id: "get-started/install",
          label: "Install Python wheel"
        },
        {
          type: "doc",
          id: "get-started/docker",
          label: "Deploy with Docker"
        },
        {
          type: "doc",
          id: "get-started/quickstart",
          label: "Quickstart"
        },
        {
          type: "doc",
          id: "get-started/tui",
          label: "Terminal User Interface (TUI)"
        },
      ],
    },
    {
      type: "category",
      label: "Core components",
      items: [
        {
          type: "doc",
          id: "core-components/agents",
          label: "Langflow Agents"
        },
        {
          type: "doc",
          id: "core-components/knowledge",
          label: "OpenSearch Knowledge"
        }
      ],
    },
    {
      type: "category",
      label: "Configuration",
      items: [
        {
          type: "doc",
          id: "configure/configuration",
          label: "Environment Variables"
        },
      ],
    },
    {
      type: "category",
      label: "Support",
      items: [
        {
          type: "doc",
          id: "support/troubleshoot",
          label: "Troubleshoot"
        },
      ],
    },
  ],
};

export default sidebars;
