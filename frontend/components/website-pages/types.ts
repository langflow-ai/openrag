export type WebsiteSource = {
  id: string;
  name: string;
  starting_url: string;
  status: "active" | "processing" | "failed";
  web_child_count?: number;
  last_successful_sync_at?: string | null;
};
