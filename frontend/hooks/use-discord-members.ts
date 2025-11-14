import * as React from "react";

interface DiscordData {
  approximate_member_count: number;
  approximate_presence_count: number;
  guild: {
    name: string;
    icon: string;
  };
}

export const useDiscordMembers = (inviteCode: string) => {
  const [data, setData] = React.useState<DiscordData | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const fetchDiscordData = async () => {
      try {
        setIsLoading(true);
        setError(null);

        const response = await fetch(
          `https://discord.com/api/v10/invites/${inviteCode}?with_counts=true&with_expiration=true`,
          {
            headers: {
              "Content-Type": "application/json",
            },
          },
        );

        if (!response.ok) {
          throw new Error(`Discord API error: ${response.status}`);
        }

        const discordData = await response.json();
        setData(discordData);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to fetch Discord data",
        );
        console.error("Discord API Error:", err);
      } finally {
        setIsLoading(false);
      }
    };

    fetchDiscordData();

    // Refresh every 10 minutes
    const interval = setInterval(fetchDiscordData, 10 * 60 * 1000);
    return () => clearInterval(interval);
  }, [inviteCode]);

  return { data, isLoading, error };
};
