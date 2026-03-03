"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { ModelProvider } from "../_helpers/model-helpers";
import CardIcon from "./card-icon";

export interface ModelProviderCardData {
  providerKey: ModelProvider;
  name: string;
  logo: (props: React.SVGProps<SVGSVGElement>) => React.ReactNode;
  logoColor: string;
  logoBgColor: string;
}

interface ModelProviderCardProps {
  provider: ModelProviderCardData;
  isConfigured: boolean;
  isUnhealthy: boolean;
  onConfigure: (providerKey: ModelProvider) => void;
}

export default function ModelProviderCard({
  provider,
  isConfigured,
  isUnhealthy,
  onConfigure,
}: ModelProviderCardProps) {
  const { providerKey, name, logo: Logo, logoColor, logoBgColor } = provider;

  return (
    <Card
      className={cn(
        "group relative flex flex-col hover:bg-secondary-hover hover:border-muted-foreground transition-colors",
        !isConfigured && "text-muted-foreground",
        isUnhealthy && "border-destructive",
      )}
    >
      <CardHeader>
        <div className="flex flex-col items-start justify-between">
          <div className="flex flex-col gap-3">
            <div className="mb-1">
              <CardIcon isActive={isConfigured} activeBgColor={logoBgColor}>
                <Logo
                  className={isConfigured ? logoColor : "text-muted-foreground"}
                />
              </CardIcon>
            </div>
            <CardTitle className="flex flex-row items-center gap-2">
              {name}
              {isUnhealthy && (
                <span className="h-2 w-2 rounded-full bg-destructive" />
              )}
            </CardTitle>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col justify-end space-y-4">
        <Button
          className={cn(
            "group-hover:bg-background",
            isConfigured && "border-primary",
          )}
          variant={isUnhealthy ? "default" : "outline"}
          onClick={() => onConfigure(providerKey)}
        >
          {isUnhealthy
            ? "Fix Setup"
            : isConfigured
              ? "Edit Setup"
              : "Configure"}
        </Button>
      </CardContent>
    </Card>
  );
}
