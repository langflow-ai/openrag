"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useIsCloudBrand } from "@/contexts/brand-context";
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
  const isCloudBrand = useIsCloudBrand();
  const { providerKey, name, logo: Logo, logoColor, logoBgColor } = provider;
  const isEditSetup = isConfigured && !isUnhealthy;

  return (
    <Card
      className={cn(
        "group relative flex flex-col transition-colors",
        isCloudBrand
          ? "rounded-none border-0 bg-layer-contextual text-layer-contextual-foreground shadow-none"
          : "hover:bg-secondary-hover hover:border-muted-foreground",
        !isConfigured && !isCloudBrand && "text-muted-foreground",
        !isConfigured && isCloudBrand && "text-layer-contextual-foreground/70",
        isUnhealthy &&
          (isCloudBrand ? "ring-2 ring-destructive" : "border-destructive"),
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
            <CardTitle
              className={cn(
                "flex flex-row items-center gap-2",
                isCloudBrand && "text-layer-contextual-foreground",
              )}
            >
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
            !isCloudBrand && "group-hover:bg-background",
            isConfigured && !isCloudBrand && "border-primary",
            isCloudBrand &&
              isEditSetup &&
              "rounded-none border border-layer-contextual-foreground bg-layer-contextual text-layer-contextual-foreground shadow-none hover:bg-layer-contextual hover:text-layer-contextual-foreground",
            isCloudBrand && !isEditSetup && !isUnhealthy && "rounded-none",
            isUnhealthy && isCloudBrand && "rounded-none",
          )}
          variant={
            isUnhealthy
              ? "default"
              : isCloudBrand && isEditSetup
                ? "ghost"
                : "outline"
          }
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
