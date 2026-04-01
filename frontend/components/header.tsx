"use client";

import { Bell } from "lucide-react";
import { BrandSwitcher } from "@/components/brand-switcher";
import Logo from "@/components/icons/openrag-logo";
import { UserNav } from "@/components/user-nav";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { useTask } from "@/contexts/task-context";
import { cn } from "@/lib/utils";

export function Header() {
  const isCloudBrand = useIsCloudBrand();
  const { tasks, toggleMenu } = useTask();

  // Calculate active tasks for the bell icon
  const activeTasks = tasks.filter(
    (task) =>
      task.status === "pending" ||
      task.status === "running" ||
      task.status === "processing",
  );

  return (
    <header className={cn(`flex w-full h-full items-center justify-between`)}>
      <div className="header-start-display px-[16px]">
        {/* Logo/Title */}
        <div className="flex items-center">
          <Logo className="fill-foreground" width={24} height={22} />
          <span
            className="text-lg font-semibold pl-2.5"
            style={{ fontFamily: '"IBM Plex Mono", monospace' }}
          >
            OpenRAG
          </span>
        </div>
      </div>
      <div className="header-end-division">
        <div className="justify-end flex items-center">
          {/* Knowledge Filter Dropdown */}
          {/* <KnowledgeFilterDropdown
              selectedFilter={selectedFilter}
              onFilterSelect={setSelectedFilter}
            /> */}

          {/* GitHub Star Button */}
          {/* <GitHubStarButton repo="phact/openrag" /> */}

          {/* Discord Link */}
          {/* <DiscordLink inviteCode="EqksyE2EX9" /> */}

          {process.env.NEXT_PUBLIC_IBM_THEME_DEV === "true" && (
            <>
              <BrandSwitcher />
              {/* Separator */}
              <div className="w-px h-6 bg-border mx-3" />
            </>
          )}

          {/* Task Notification Bell */}
          <button
            onClick={toggleMenu}
            data-testid="task-menu-toggle"
            className="relative h-8 w-8 hover:bg-muted rounded-lg flex items-center justify-center"
          >
            <Bell
              size={16}
              className={
                isCloudBrand ? "text-foreground" : "text-muted-foreground"
              }
            />
            {activeTasks.length > 0 && <div className="header-notifications" />}
          </button>

          {/* Separator */}
          <div className="w-px h-6 bg-border mx-3" />

          <UserNav />
        </div>
      </div>
    </header>
  );
}
