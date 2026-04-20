"use client";

import { Loader2, Plus, RefreshCcw, Settings2, Trash2 } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { cn } from "@/lib/utils";
import CardIcon from "./card-icon";

export interface Connector {
  id: string;
  name: string;
  type: string;
  icon: React.ReactNode;
  available?: boolean;
  status?: string;
  connectionId?: string;
}

interface ConnectorCardProps {
  connector: Connector;
  isConnecting: boolean;
  isDisconnecting: boolean;
  onConnect: (connector: Connector) => void;
  onDisconnect: (connector: Connector) => void;
  onNavigateToKnowledge: (connector: Connector) => void;
  /** Optional: open a connector-specific settings/edit dialog */
  onConfigure?: (connector: Connector) => void;
}

export default function ConnectorCard({
  connector,
  isConnecting,
  isDisconnecting,
  onConnect,
  onDisconnect,
  onNavigateToKnowledge,
  onConfigure,
}: ConnectorCardProps) {
  const isCloudBrand = useIsCloudBrand();
  const isConnected =
    connector.status === "connected" && connector.connectionId;

  return (
    <Card
      className={cn(
        "group relative flex flex-col transition-colors",
        isCloudBrand
          ? "rounded-none border-0 bg-layer-contextual text-layer-contextual-foreground shadow-none hover:bg-layer-contextual"
          : "hover:bg-secondary-hover hover:border-muted-foreground",
      )}
    >
      <CardHeader className="pb-2">
        <div className="flex flex-col items-start justify-between">
          <div className="flex flex-col gap-4 mb-2 w-full">
            <div className="flex items-center justify-between mb-1">
              <CardIcon isActive={!!isConnected} activeBgColor="bg-white">
                {connector.icon}
              </CardIcon>
              {isConnected ? (
                <div
                  className={cn(
                    "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
                    isCloudBrand
                      ? "bg-primary/10 text-primary dark:bg-white/10 dark:text-layer-contextual-foreground"
                      : "bg-foreground text-muted",
                  )}
                >
                  <span className="h-2 w-2 rounded-full bg-green-500" />
                  Active
                </div>
              ) : null}
            </div>
            <div>
              <CardTitle
                className={cn(
                  "flex flex-row items-center",
                  isCloudBrand && "text-layer-contextual-foreground",
                )}
              >
                {connector.name}
              </CardTitle>
              <CardDescription
                className={cn(
                  "text-sm",
                  isCloudBrand && "!text-layer-contextual-foreground",
                )}
              >
                {isConnected || connector?.available
                  ? `${connector.name} is configured.`
                  : "Not configured."}
              </CardDescription>
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col justify-end space-y-4">
        {connector?.available ? (
          <div className="space-y-3">
            {isConnected ? (
              <div className="flex gap-2 overflow-hidden w-full">
                <Button
                  variant="default"
                  onClick={() => onNavigateToKnowledge(connector)}
                  disabled={isDisconnecting || isConnecting}
                  className={cn(
                    "cursor-pointer !text-sm truncate flex-1 text-primary-foreground [&_svg]:text-primary-foreground",
                    isCloudBrand ? "rounded-none" : "rounded-md",
                  )}
                  size="md"
                >
                  <Plus className="h-4 w-4" />
                  <span className="text-mmd truncate">Add Knowledge</span>
                </Button>
                <Button
                  variant="outline"
                  onClick={() =>
                    onConfigure ? onConfigure(connector) : onConnect(connector)
                  }
                  disabled={isConnecting || isDisconnecting}
                  className={cn(
                    "cursor-pointer",
                    isCloudBrand &&
                      "rounded-none border-button-tertiary text-layer-contextual-foreground hover:bg-black/5 hover:text-layer-contextual-foreground dark:hover:bg-white/5",
                  )}
                  size="iconMd"
                >
                  {isConnecting ? (
                    <RefreshCcw className="h-4 w-4 animate-spin" />
                  ) : (
                    <Settings2 className="h-4 w-4" />
                  )}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => onDisconnect(connector)}
                  disabled={isDisconnecting || isConnecting}
                  className={cn(
                    "cursor-pointer text-destructive hover:text-destructive",
                    isCloudBrand && "rounded-none",
                  )}
                  size="iconMd"
                >
                  {isDisconnecting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                </Button>
              </div>
            ) : (
              <Button
                onClick={() =>
                  onConfigure ? onConfigure(connector) : onConnect(connector)
                }
                disabled={isConnecting}
                variant={isCloudBrand ? "outline" : "default"}
                className={cn(
                  "w-full cursor-pointer",
                  isCloudBrand
                    ? "rounded-none border-layer-contextual-foreground bg-layer-contextual text-layer-contextual-foreground hover:bg-primary hover:text-primary-foreground hover:border-primary"
                    : "group-hover:bg-background group-hover:border-zinc-700 group-hover:text-primary",
                )}
                size="sm"
              >
                {isConnecting ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Connecting...
                  </>
                ) : (
                  <>Connect</>
                )}
              </Button>
            )}
          </div>
        ) : (
          <div
            className={cn(
              "text-sm",
              isCloudBrand
                ? "text-layer-contextual-foreground"
                : "text-muted-foreground",
            )}
          >
            <p>For more details see our</p>
            <Link
              className={
                isCloudBrand
                  ? "underline-offset-2"
                  : "text-accent-pink-foreground"
              }
              href="https://docs.openr.ag/knowledge#oauth-ingestion"
              target="_blank"
              rel="noopener noreferrer"
            >
              Cloud Connectors guide
            </Link>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
