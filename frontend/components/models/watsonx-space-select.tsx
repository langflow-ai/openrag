"use client";

import { Check, ChevronsUpDown, LoaderCircle, Plus, X } from "lucide-react";
import { useEffect, useId, useReducer, useState } from "react";
import { LabelWrapper } from "@/components/label-wrapper";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

interface WatsonxSpace {
  id: string;
  name: string;
}

interface WatsonxSpaceSelectProps {
  credentials: Record<string, string>;
  authMethod?: string;
  hasSavedApiKey?: boolean;
  hasSavedZenApiKey?: boolean;
  value?: string;
  onValueChange: (value: string) => void;
  helperText?: string;
  idPrefix: string;
}

type SpaceSelectState = {
  open: boolean;
  spaces: WatsonxSpace[];
  status: "idle" | "loading" | "loaded";
  error: string | null;
};

type SpaceSelectAction =
  | { type: "reset" }
  | { type: "loading" }
  | { type: "loaded"; spaces: WatsonxSpace[] }
  | { type: "failed"; error: string }
  | { type: "setOpen"; open: boolean };

const initialState: SpaceSelectState = {
  open: false,
  spaces: [],
  status: "idle",
  error: null,
};

function reduceSpaceSelect(
  state: SpaceSelectState,
  action: SpaceSelectAction,
): SpaceSelectState {
  switch (action.type) {
    case "reset":
      return initialState;
    case "loading":
      return { ...state, spaces: [], status: "loading", error: null };
    case "loaded":
      return { ...state, spaces: action.spaces, status: "loaded", error: null };
    case "failed":
      return { ...state, status: "loaded", error: action.error };
    case "setOpen":
      return { ...state, open: action.open };
  }
}

export function WatsonxSpaceSelect({
  credentials,
  authMethod = "username_api_key",
  hasSavedApiKey = false,
  hasSavedZenApiKey = false,
  value = "",
  onValueChange,
  helperText,
  idPrefix,
}: WatsonxSpaceSelectProps) {
  const generatedId = useId();
  const id = `${idPrefix}-space-${generatedId.replaceAll(":", "")}`;
  const [state, dispatch] = useReducer(reduceSpaceSelect, initialState);
  const [search, setSearch] = useState("");
  const { open, spaces, status, error } = state;

  const apiBase = credentials.api_base?.trim() ?? "";
  const username = credentials.username?.trim() ?? "";
  const apiKey = credentials.api_key ?? "";
  const zenApiKey = credentials.zen_api_key ?? "";
  const sslVerify = credentials.ssl_verify ?? "";
  const ready =
    Boolean(apiBase) &&
    (authMethod === "zen_api_key"
      ? Boolean(zenApiKey.trim() || hasSavedZenApiKey)
      : Boolean(username && (apiKey.trim() || hasSavedApiKey)));

  useEffect(() => {
    if (!ready) {
      dispatch({ type: "reset" });
      return;
    }

    const controller = new AbortController();
    dispatch({ type: "loading" });

    const timeout = window.setTimeout(async () => {
      try {
        const submittedCredentials = Object.fromEntries(
          Object.entries({
            api_base: apiBase,
            username,
            api_key: apiKey,
            zen_api_key: zenApiKey,
            ssl_verify: sslVerify,
          }).filter(([, credentialValue]) => credentialValue !== ""),
        );
        const response = await fetch("/api/models/watsonx_onprem/spaces", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            credentials: submittedCredentials,
            auth_method: authMethod,
          }),
          signal: controller.signal,
        });
        const result = (await response.json()) as {
          spaces?: WatsonxSpace[];
          error?: string;
        };
        if (!response.ok) {
          throw new Error(result.error || "Could not load deployment spaces");
        }
        dispatch({ type: "loaded", spaces: result.spaces ?? [] });
      } catch (requestError) {
        if (controller.signal.aborted) return;
        dispatch({
          type: "failed",
          error:
            requestError instanceof Error
              ? requestError.message
              : "Could not load deployment spaces",
        });
      }
    }, 350);

    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [apiBase, username, apiKey, zenApiKey, sslVerify, authMethod, ready]);

  const selected = spaces.find((space) => space.id === value);
  const selectedLabel = selected?.name ?? value;
  const typedSpaceId = search.trim();
  const typedSpaceExists = spaces.some(
    (space) => space.id.toLowerCase() === typedSpaceId.toLowerCase(),
  );

  const selectSpace = (spaceId: string) => {
    onValueChange(spaceId);
    setSearch("");
    dispatch({ type: "setOpen", open: false });
  };

  return (
    <div className="min-w-0 space-y-2">
      <LabelWrapper label="Deployment space ID" helperText={helperText} id={id}>
        <div className="flex min-w-0 gap-2">
          <Popover
            open={open}
            onOpenChange={(nextOpen) => {
              dispatch({ type: "setOpen", open: nextOpen });
              if (!nextOpen) setSearch("");
            }}
          >
            <PopoverTrigger asChild>
              <Button
                id={id}
                type="button"
                variant="outline"
                role="combobox"
                aria-expanded={open}
                aria-busy={status === "loading"}
                disabled={!ready}
                className="min-w-0 flex-1 justify-between px-3 font-normal normal-case"
                ignoreTitleCase
              >
                <span className="min-w-0 truncate text-left">
                  {status === "loading"
                    ? "Loading deployment spaces…"
                    : selectedLabel || "Select a deployment space"}
                </span>
                {status === "loading" ? (
                  <LoaderCircle className="animate-spin opacity-60" />
                ) : (
                  <ChevronsUpDown className="opacity-50" />
                )}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0">
              <Command>
                <CommandInput
                  placeholder="Search or enter a deployment space ID…"
                  value={search}
                  onValueChange={setSearch}
                />
                <CommandList>
                  <CommandEmpty>
                    No accessible deployment spaces. Enter an ID to use it.
                  </CommandEmpty>
                  <CommandGroup>
                    {typedSpaceId && !typedSpaceExists && (
                      <CommandItem
                        value={typedSpaceId}
                        onSelect={() => selectSpace(typedSpaceId)}
                        className="gap-2 py-2"
                      >
                        <Plus />
                        <span className="min-w-0 truncate">
                          Use <span className="font-mono">{typedSpaceId}</span>{" "}
                          as deployment space ID
                        </span>
                      </CommandItem>
                    )}
                    {spaces.map((space) => (
                      <CommandItem
                        key={space.id}
                        value={`${space.name} ${space.id}`}
                        onSelect={() => selectSpace(space.id)}
                        className="items-start gap-2 py-2"
                      >
                        <Check
                          className={cn(
                            "mt-0.5",
                            space.id === value ? "opacity-100" : "opacity-0",
                          )}
                        />
                        <span className="min-w-0">
                          <span className="block truncate">{space.name}</span>
                          <span className="block truncate font-mono text-xs text-muted-foreground">
                            {space.id}
                          </span>
                        </span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
          {value && (
            <Button
              type="button"
              variant="ghost"
              size="iconMd"
              aria-label="Clear deployment space"
              onClick={() => onValueChange("")}
            >
              <X />
            </Button>
          )}
        </div>
      </LabelWrapper>
      {!ready && (
        <p className="text-sm text-muted-foreground">
          Enter connection credentials to load deployment spaces.
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
