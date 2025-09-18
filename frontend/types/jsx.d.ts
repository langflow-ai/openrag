import React from 'react';

declare global {
  namespace JSX {
    interface IntrinsicElements {
      [elemName: string]: any;
    }
  }
}

declare module 'react-markdown' {
  interface ReactMarkdownProps {
    children: string;
    remarkPlugins?: any[];
    rehypePlugins?: any[];
    linkTarget?: string;
    components?: any;
  }

  const ReactMarkdown: React.FC<ReactMarkdownProps>;
  export default ReactMarkdown;
}