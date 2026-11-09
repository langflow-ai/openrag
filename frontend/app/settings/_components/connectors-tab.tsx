"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { cn } from "@/lib/utils";
import ConnectorCards from "./connector-cards";

export function ConnectorsTab() {
  const isCloudBrand = useIsCloudBrand();
  const { isNoAuthMode } = useAuth();

  return (
    <div className="space-y-6">
      {isNoAuthMode && (
        <Card className="border-accent-amber-foreground">
          <CardHeader>
            <CardTitle
              className={cn(
                "text-lg",
                isCloudBrand && "ibm-settings-section-title",
              )}
            >
              Cloud connectors require authentication
            </CardTitle>
            <CardDescription className="text-sm">
              Add the Google OAuth variables below to your <code>.env</code>{" "}
              then restart the OpenRAG containers.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="bg-muted rounded-md p-4 font-mono text-sm overflow-x-auto">
              <div className="text-muted-foreground">
                <div>
                  <span className="mr-3 text-placeholder-foreground">27</span>
                  <span># Google OAuth</span>
                </div>
                <div>
                  <span className="mr-3 text-placeholder-foreground">28</span>
                  <span># Create credentials here:</span>
                </div>
                <div className="flex flex-wrap">
                  <span className="mr-3 text-placeholder-foreground shrink-0">
                    29
                  </span>
                  <span className="break-all">
                    # https://console.cloud.google.com/apis/credentials
                  </span>
                </div>
              </div>
              <div>
                <span className="mr-3 text-placeholder-foreground">30</span>
                <span>GOOGLE_OAUTH_CLIENT_ID=</span>
              </div>
              <div>
                <span className="mr-3 text-placeholder-foreground">31</span>
                <span>GOOGLE_OAUTH_CLIENT_SECRET=</span>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
      <ConnectorCards />
    </div>
  );
}
