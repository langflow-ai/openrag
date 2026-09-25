export type Scope = "path" | "page" | "site";

export type UrlSourceForm = {
  name: string;
  starting_url: string;
  scope: Scope;
  allow_subdomains: boolean;
  additional_hosts: string;
  include_paths: string;
  exclude_paths: string;
  max_pages: number;
  max_depth: number;
  max_downloaded_mb: number;
  max_crawl_minutes: number;
  resync_behavior: "full" | "root";
  removed_page_behavior: "retain" | "delete";
};

export type UpdateUrlSourceForm = <K extends keyof UrlSourceForm>(
  key: K,
  value: UrlSourceForm[K],
) => void;

export const INITIAL_URL_SOURCE_FORM: UrlSourceForm = {
  name: "",
  starting_url: "",
  scope: "path",
  allow_subdomains: false,
  additional_hosts: "",
  include_paths: "",
  exclude_paths: "",
  max_pages: 250,
  max_depth: 4,
  max_downloaded_mb: 128,
  max_crawl_minutes: 15,
  resync_behavior: "full",
  removed_page_behavior: "retain",
};

export function lines(value: string) {
  return value.split("\n").flatMap((line) => {
    const trimmed = line.trim();
    return trimmed ? [trimmed] : [];
  });
}

function validUrl(value: string) {
  try {
    const url = new URL(value);
    return (
      ["http:", "https:"].includes(url.protocol) &&
      !url.username &&
      !url.password &&
      (!url.port || url.port === "80" || url.port === "443") &&
      !/^\d{1,3}(\.\d{1,3}){3}$/.test(url.hostname) &&
      !url.hostname.includes(":")
    );
  } catch {
    return false;
  }
}

export function isUrlSourceFormValid(form: UrlSourceForm) {
  return Boolean(
    form.name.trim() &&
      validUrl(form.starting_url) &&
      lines(form.additional_hosts).every(
        (host) => !host.includes("/") && !/^\d{1,3}(\.\d{1,3}){3}$/.test(host),
      ) &&
      [...lines(form.include_paths), ...lines(form.exclude_paths)].every(
        (path) => path.startsWith("/"),
      ),
  );
}

export function createUrlSourcePayload(form: UrlSourceForm) {
  const pageScope = form.scope === "page";
  return {
    ...form,
    additional_hosts: lines(form.additional_hosts),
    include_paths: lines(form.include_paths),
    exclude_paths: lines(form.exclude_paths),
    max_pages: pageScope ? 1 : form.max_pages,
    max_depth: pageScope ? 0 : form.max_depth,
  };
}
