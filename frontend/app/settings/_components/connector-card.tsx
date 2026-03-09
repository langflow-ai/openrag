"use client";

import { Loader2, Plus, RefreshCcw, Trash2 } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
}

export default function ConnectorCard({
  connector,
  isConnecting,
  isDisconnecting,
  onConnect,
  onDisconnect,
  onNavigateToKnowledge,
}: ConnectorCardProps) {
  console.log(connector);
  const isConnected =
    connector?.name === "Google Drive" ||
    (connector?.status === "connected" && connector?.connectionId);

  return (
    <Card className="group relative flex flex-col hover:bg-secondary-hover hover:border-muted-foreground transition-colors">
      <CardHeader className="pb-2">
        <div className="flex flex-col items-start justify-between">
          <div className="flex flex-col gap-4 mb-2 w-full">
            <div className="flex items-center justify-between mb-1">
              <CardIcon
                isActive={!!(connector?.available && isConnected)}
                activeBgColor="bg-white"
              >
                {connector.icon}
              </CardIcon>
              {isConnected ? (
                <div className="flex items-center gap-1.5 rounded-full bg-foreground px-2.5 py-1 text-xs font-medium text-muted">
                  <span className="h-2 w-2 rounded-full bg-green-500" />
                  Active
                </div>
              ) : null}
            </div>
            <div>
              <CardTitle className="flex flex-row items-center">
                {connector.name}
              </CardTitle>
              <CardDescription className="text-sm">
                {connector?.available
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
                  className="cursor-pointer !text-sm truncate rounded-md"
                  size="md"
                >
                  <Plus className="h-4 w-4" />
                  <span className="text-mmd truncate">Add Knowledge</span>
                </Button>
                <Button
                  variant="outline"
                  onClick={() => onConnect(connector)}
                  disabled={isConnecting || isDisconnecting}
                  className="cursor-pointer"
                  size="iconMd"
                >
                  {isConnecting ? (
                    <RefreshCcw className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCcw className="h-4 w-4" />
                  )}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => onDisconnect(connector)}
                  disabled={isDisconnecting || isConnecting}
                  className="cursor-pointer text-destructive hover:text-destructive"
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
                onClick={() => onConnect(connector)}
                disabled={isConnecting}
                className="w-full cursor-pointer group-hover:bg-background group-hover:border-zinc-700 group-hover:text-primary"
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
          <div className="text-sm text-muted-foreground">
            <p>
              See our{" "}
              <Link
                className="text-accent-pink-foreground"
                href="https://docs.openr.ag/knowledge#oauth-ingestion"
                target="_blank"
                rel="noopener noreferrer"
              >
                Cloud Connectors installation guide
              </Link>{" "}
              for more detail.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
