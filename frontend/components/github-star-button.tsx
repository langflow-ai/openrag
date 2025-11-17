"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Github } from "lucide-react";
import { useGitHubStars } from "@/hooks/use-github-stars";
import { formatCount } from "@/lib/format-count";

interface GitHubStarButtonProps {
  repo?: string;
  className?: string;
}

const GitHubStarButton = React.forwardRef<
  HTMLAnchorElement,
  GitHubStarButtonProps
>(({ repo = "phact/openrag", className }, ref) => {
  const { data, isLoading, error } = useGitHubStars(repo);

  return (
    <a
      ref={ref}
      href={`https://github.com/${repo}`}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        "inline-flex h-8 items-center justify-center rounded-md px-2 text-sm font-medium text-muted-foreground shadow-sm transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        className,
      )}
    >
      <Github className="h-4 w-4" />
      <span className="hidden sm:inline ml-2">
        {isLoading
          ? "..."
          : error
            ? "--"
            : data
              ? formatCount(data.stargazers_count)
              : "--"}
      </span>
    </a>
  );
});

GitHubStarButton.displayName = "GitHubStarButton";

export { GitHubStarButton };
