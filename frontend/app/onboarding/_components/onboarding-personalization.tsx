"use client";

import { UserRound } from "lucide-react";
import { useState } from "react";
import { useUpdateDisplayNameMutation } from "@/app/api/mutations/useUpdateDisplayNameMutation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/contexts/auth-context";

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

  // Prefill from display_name, then OAuth name (skip "Anonymous User" default)
  const rawName =
    user?.display_name ||
    (user?.name !== "Anonymous User" ? user?.name : "") ||
    "";
  const initialName = rawName.split(/\s+/)[0] ?? "";
  const [value, setValue] = useState(initialName);

  const handleSave = async () => {
    const trimmed = value.trim();
    await updateDisplayName.mutateAsync({ display_name: trimmed || null });
    await refreshAuth();
    onComplete();
  };

  return (
    <div className="flex flex-col gap-5 w-full max-w-sm">
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <UserRound className="h-4 w-4" />
          <span>What should we call you?</span>
        </div>
        <Input
          value={value}
          onChange={(e) => setValue(e.target.value)}
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
