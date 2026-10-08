import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test-utils/msw/server";
import { renderWithProviders } from "@/test-utils/render";
import { UrlSourceDialog } from "./url-source-dialog";

describe("UrlSourceDialog", () => {
  it("switches between source and re-sync steps from the dialog header", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/connectors/url/sources", () =>
        HttpResponse.json({ sources: [] }),
      ),
    );

    renderWithProviders(<UrlSourceDialog open onOpenChange={vi.fn()} />);

    const sourceTab = screen.getByRole("button", { name: "Source & scope" });
    const resyncTab = screen.getByRole("button", { name: "Re-sync behavior" });

    expect(sourceTab).toHaveAttribute("aria-current", "step");
    expect(
      screen.getByRole("heading", { name: "Where should we crawl?" }),
    ).toBeInTheDocument();

    await user.click(resyncTab);

    expect(resyncTab).toHaveAttribute("aria-current", "step");
    expect(
      screen.getByRole("heading", { name: "How should re-syncs work?" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Back" }),
    ).not.toBeInTheDocument();

    await user.click(sourceTab);

    expect(sourceTab).toHaveAttribute("aria-current", "step");
    expect(
      screen.getByRole("heading", { name: "Where should we crawl?" }),
    ).toBeInTheDocument();
  });

  it("submits normalized settings after configuring the source and re-sync behavior", async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();
    let requestBody: Record<string, unknown> | undefined;
    server.use(
      http.get("/api/connectors/url/sources", () =>
        HttpResponse.json({ sources: [] }),
      ),
      http.post("/api/connectors/url/sources", async ({ request }) => {
        requestBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ last_task_id: "website-task" });
      }),
    );

    renderWithProviders(
      <UrlSourceDialog open onOpenChange={vi.fn()} onCreated={onCreated} />,
    );

    const continueButton = screen.getByRole("button", { name: "Continue" });
    expect(continueButton).toBeDisabled();

    await user.type(screen.getByLabelText("Connection name"), "Docs");
    await user.type(
      screen.getByLabelText("Starting URL"),
      "https://docs.example.com/guides",
    );
    await user.click(screen.getByRole("button", { name: /This page only/ }));
    await user.click(
      screen.getByRole("button", { name: "Advanced crawl settings" }),
    );
    await user.type(
      screen.getByPlaceholderText("assets.example.com (one per line)"),
      "assets.example.com\ncdn.example.com",
    );
    await user.type(
      screen.getByPlaceholderText("/docs/ (one per line)"),
      "/guides",
    );
    await user.type(
      screen.getByPlaceholderText("/archive/ (one per line)"),
      "/archive",
    );
    await user.click(screen.getByLabelText("Change detection"));
    await user.click(screen.getByRole("option", { name: "Always re-ingest" }));
    await user.click(screen.getByRole("checkbox"));

    expect(continueButton).toBeEnabled();
    const limits = screen.getAllByRole("spinbutton");
    expect(limits[0]).toBeDisabled();
    expect(limits[1]).toBeDisabled();

    await user.click(continueButton);
    await user.click(
      screen.getByRole("button", { name: /Ingest only root page/ }),
    );
    await user.click(
      screen.getByRole("button", { name: /Full crawl; ingest returned pages/ }),
    );
    await user.click(screen.getByRole("button", { name: /Retain in corpus/ }));
    await user.click(screen.getByRole("button", { name: /Delete/ }));
    await user.click(screen.getByRole("button", { name: /Ingest URL/i }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("website-task"));
    expect(requestBody).toMatchObject({
      name: "Docs",
      scope: "page",
      additional_hosts: ["assets.example.com", "cdn.example.com"],
      include_paths: ["/guides"],
      change_detection: "always_reingest",
      max_pages: 1,
      max_depth: 0,
      removed_page_behavior: "delete",
    });
  });

  it("reports an existing website connection name before submission", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/connectors/url/sources", () =>
        HttpResponse.json({
          sources: [
            {
              id: "source-1",
              name: "Docs",
              starting_url: "https://docs.example.com",
              status: "active",
            },
          ],
        }),
      ),
    );

    renderWithProviders(<UrlSourceDialog open onOpenChange={vi.fn()} />);

    await user.type(screen.getByLabelText("Connection name"), " docs ");

    expect(
      await screen.findByText(
        "A website connection with this name already exists.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });
});
