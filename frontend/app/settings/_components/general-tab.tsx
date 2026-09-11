"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useUpdateDisplayNameMutation } from "@/app/api/mutations/useUpdateDisplayNameMutation";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { cn } from "@/lib/utils";
import { saveDisplayName } from "./general-tab.helpers";

export function GeneralTab() {
  const isCloudBrand = useIsCloudBrand();
  const { user, refreshAuth } = useAuth();
  const updateDisplayName = useUpdateDisplayNameMutation();

  const [value, setValue] = useState(user?.display_name ?? "");
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    if (!touched && user?.display_name !== undefined) {
      setValue(user.display_name ?? "");
    }
  }, [user?.display_name, touched]);

  const isDirty = value !== (user?.display_name ?? "");

  const handleSave = () =>
    saveDisplayName(value, {
      mutateAsync: updateDisplayName.mutateAsync,
      refreshAuth,
      onSuccess: toast.success,
      onError: toast.error,
    });

  return (
    <div className={cn("space-y-6", isCloudBrand && "ibm-settings-content")}>
      <Card className={cn(isCloudBrand && "ibm-card")}>
        <CardContent className="space-y-4">
          <div className="space-y-2 mt-3">
            <Label htmlFor="display-name" className="font-medium text-sm">
              Display name
            </Label>
            <p className="text-mmd text-muted-foreground">
              Used in the chat greeting. Leave blank to use your account name.
            </p>
            <div className="flex items-center gap-3 max-w-sm">
              <Input
                id="display-name"
                value={value}
                onChange={(e) => {
                  setTouched(true);
                  setValue(e.target.value);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && isDirty) handleSave();
                }}
                placeholder={user?.name ?? "e.g. Alex"}
                maxLength={80}
                className="text-sm"
              />
              <Button
                size="sm"
                onClick={handleSave}
                disabled={!isDirty || updateDisplayName.isPending}
                loading={updateDisplayName.isPending}
              >
                Save
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
