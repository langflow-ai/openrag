import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { tomorrow } from "react-syntax-highlighter/dist/cjs/styles/prism";
import { Button } from "./ui/button";

type CodeComponentProps = {
  code: string;
  language: string;
};

export default function CodeComponent({ code, language }: CodeComponentProps) {
  const [isCopied, setIsCopied] = useState<boolean>(false);

  const copyToClipboard = () => {
    if (!navigator.clipboard || !navigator.clipboard.writeText) {
      return;
    }

    navigator.clipboard.writeText(code).then(() => {
      setIsCopied(true);

      setTimeout(() => {
        setIsCopied(false);
      }, 2000);
    });
  };

  return (
    <div
      className="mt-2 relative flex w-full flex-col overflow-hidden rounded-md text-left dark"
      data-testid="chat-code-tab"
    >
      <Button
        variant="ghost"
        size="icon"
        className="text-muted-foreground hover:bg-card absolute top-2 right-2"
        data-testid="copy-code-button"
        onClick={copyToClipboard}
      >
        {isCopied ? (
          <Check className="h-4 w-4" />
        ) : (
          <Copy className="h-4 w-4" />
        )}
      </Button>
      <SyntaxHighlighter
        language={language.toLowerCase()}
        style={tomorrow}
        className="!mt-0 h-full w-full overflow-scroll !rounded-b-md !rounded-t-none border border-border text-left !custom-scroll !text-sm"
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}
