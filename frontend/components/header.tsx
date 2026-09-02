"use client";

import { Bell } from "lucide-react";
import { BrandSwitcher } from "@/components/brand-switcher";
import { ConsoleStatusButton } from "@/components/console-status";
import { DevRoleToggle } from "@/components/dev-role-toggle";
import Logo from "@/components/icons/bomarag-logo";
import { UserNav } from "@/components/user-nav";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import {
  useConsoleStatus,
  useToggleTaskMenu,
} from "@/contexts/console-status-context";
import { useTask } from "@/contexts/task-context";
import { cn } from "@/lib/utils";
import { useProviderHealth } from "./provider-health-banner";

export function Header() {
  const isCloudBrand = useIsCloudBrand();
  const { tasks } = useTask();
  const toggleTaskMenu = useToggleTaskMenu();
  const { runMode } = useAuth();

  const {
    hasProblem,
    toggle,
    isOpen,
    overallStatus: consoleOverallStatus,
  } = useConsoleStatus();
  const { isUnhealthy: isProviderUnhealthy } = useProviderHealth();
  const overallStatus = isProviderUnhealthy
    ? "unhealthy"
    : consoleOverallStatus;

  // Calculate active tasks for the bell icon
  const activeTasks = tasks.filter(
    (task) =>
      task.status === "pending" ||
      task.status === "running" ||
      task.status === "processing",
  );

  // The bell dot lights for in-flight tasks OR a degraded/down component.
  const showNotificationDot = activeTasks.length > 0 || hasProblem;

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
            BomaRAG
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
          {/* <GitHubStarButton repo="phact/bomarag" /> */}

          {/* Discord Link */}
          {/* <DiscordLink inviteCode="EqksyE2EX9" /> */}

          {process.env.NEXT_PUBLIC_IBM_THEME_DEV === "true" && (
            <>
              <BrandSwitcher />
              <DevRoleToggle />
              {/* Separator */}
              <div className="w-px h-6 bg-border mx-3" />
            </>
          )}

          {/* Console Status button — OSS only */}
          {runMode === "oss" && (
            <>
              <ConsoleStatusButton
                onClick={toggle}
                isOpen={isOpen}
                overallStatus={overallStatus}
              />
              <div className="w-px h-6 bg-border mx-3" />
            </>
          )}

          {/* Task + System Notification Bell */}
          <button
            type="button"
            onClick={toggleTaskMenu}
            data-testid="task-menu-toggle"
            className="relative h-8 w-8 hover:bg-muted rounded-lg flex items-center justify-center"
          >
            <Bell
              size={16}
              className={
                isCloudBrand ? "text-foreground" : "text-muted-foreground"
              }
            />
            {showNotificationDot && <div className="header-notifications" />}
          </button>

          {/* Separator */}
          <div className="w-px h-6 bg-border mx-3" />

          <UserNav />
        </div>
      </div>
    </header>
  );
}
