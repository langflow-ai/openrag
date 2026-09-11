"use client";

import { UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useUpdateDisplayNameMutation } from "@/app/api/mutations/useUpdateDisplayNameMutation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/contexts/auth-context";
import { resolveDisplayName } from "@/lib/user";
import { saveDisplayName } from "./onboarding-personalization.helpers";

interface OnboardingPersonalizationProps {
  onComplete: () => void;
  onSkip: () => void;
}

export function OnboardingPersonalization({
  onComplete,
  onSkip,
}: OnboardingPersonalizationProps) {
  const { user, refreshAuth } = useAuth();
  const updateDisplayName = useUpdateDisplayNameMutation();

  const initialName = (resolveDisplayName(user) ?? "").split(/\s+/)[0];
  const [value, setValue] = useState(initialName);
  const touchedRef = useRef(false);

  // Backfill the input once auth resolves, but only if the user has not
  // typed anything yet. Using a ref avoids the extra render that
  // useState(touched) + useEffect would cause.
  useEffect(() => {
    if (!touchedRef.current) {
      setValue((resolveDisplayName(user) ?? "").split(/\s+/)[0]);
    }
  }, [user]);

  const handleSave = () =>
    saveDisplayName(value, {
      mutateAsync: updateDisplayName.mutateAsync,
      refreshAuth,
      onComplete,
      onError: toast.error,
    });

  return (
    <div className="flex flex-col gap-5 w-full max-w-sm">
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <UserRound className="h-4 w-4" />
          <span>What should we call you?</span>
        </div>
        <Input
          value={value}
          onChange={(e) => {
            touchedRef.current = true;
            setValue(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSave();
          }}
          placeholder="e.g. John"
          maxLength={80}
          autoFocus
          className="text-sm"
          data-testid="personalization-name-input"
        />
        <p className="text-xs text-muted-foreground">
          This is used to personalize your greeting. You can change it later in
          settings.
        </p>
      </div>

      <div className="flex items-center gap-3">
        <Button
          size="sm"
          onClick={handleSave}
          loading={updateDisplayName.isPending}
          disabled={updateDisplayName.isPending}
          data-testid="personalization-save-button"
        >
          Save
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={onSkip}
          disabled={updateDisplayName.isPending}
          className="text-muted-foreground"
          data-testid="personalization-skip-button"
        >
          Skip
        </Button>
      </div>
    </div>
  );
}
