"use client";

import React from "react";

// Type-safe wrapper that bypasses react-markdown typing issues
interface MarkdownWrapperProps {
  children: string;
  remarkPlugins?: any[];
  rehypePlugins?: any[];
  linkTarget?: string;
  components?: any;
}

const MarkdownWrapper: React.FC<MarkdownWrapperProps> = ({
  children,
  remarkPlugins,
  rehypePlugins,
  linkTarget,
  components
}) => {
  const [MarkdownComponent, setMarkdownComponent] = React.useState<any>(null);

  React.useEffect(() => {
    // Dynamically import react-markdown at runtime to avoid build-time type issues
    import("react-markdown").then((mod) => {
      setMarkdownComponent(() => mod.default);
    });
  }, []);

  if (!MarkdownComponent) {
    return <div>Loading markdown...</div>;
  }

  return React.createElement(MarkdownComponent, {
    remarkPlugins,
    rehypePlugins,
    linkTarget,
    components,
    children,
  });
};

export default MarkdownWrapper;