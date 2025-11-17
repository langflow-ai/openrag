import * as React from "react";

interface GitHubData {
  stargazers_count: number;
  forks_count: number;
  open_issues_count: number;
}

export const useGitHubStars = (repo: string) => {
  const [data, setData] = React.useState<GitHubData | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const fetchGitHubData = async () => {
      try {
        setIsLoading(true);
        setError(null);

        const response = await fetch(`https://api.github.com/repos/${repo}`, {
          headers: {
            Accept: "application/vnd.github.v3+json",
            // Optional: Add your GitHub token for higher rate limits
            // 'Authorization': `Bearer ${process.env.NEXT_PUBLIC_GITHUB_TOKEN}`,
          },
        });

        if (!response.ok) {
          throw new Error(`GitHub API error: ${response.status}`);
        }

        const repoData = await response.json();
        setData(repoData);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to fetch GitHub data",
        );
        console.error("GitHub API Error:", err);
      } finally {
        setIsLoading(false);
      }
    };

    fetchGitHubData();

    // Refresh every 5 minutes
    const interval = setInterval(fetchGitHubData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [repo]);

  return { data, isLoading, error };
};
