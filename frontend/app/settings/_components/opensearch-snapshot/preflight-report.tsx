"use client";

import { AlertTriangle, Info } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  type AnalyserFileRef,
  type AnalyserFileUpload,
  formatBytes,
  type PreflightIssue,
  type PreflightResult,
} from "@/lib/opensearch-snapshot";

export const analyserKey = (ref: Pick<AnalyserFileRef, "index" | "setting">) =>
  `${ref.index}\u0000${ref.setting}`;

/** Uploads in the shape the API expects; refs without content are skipped. */
export function buildAnalyserUploads(
  refs: AnalyserFileRef[],
  contents: Record<string, string>,
): AnalyserFileUpload[] {
  return refs.flatMap((ref) => {
    const content = contents[analyserKey(ref)];
    return content === undefined
      ? []
      : [{ index: ref.index, setting: ref.setting, content }];
  });
}

export function missingAnalyserFiles(
  refs: AnalyserFileRef[],
  contents: Record<string, string>,
): AnalyserFileRef[] {
  return refs.filter((ref) => contents[analyserKey(ref)] === undefined);
}

function readFileText(file: File): Promise<string> {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

function IssueList({
  issues,
  title,
  destructive,
}: {
  issues: PreflightIssue[];
  title: string;
  destructive?: boolean;
}) {
  if (issues.length === 0) return null;
  return (
    <Alert variant={destructive ? "destructive" : "default"}>
      <AlertTriangle />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <ul className="list-disc pl-4 space-y-1">
          {issues.map((issue) => (
            <li key={`${issue.code}-${issue.index ?? ""}-${issue.message}`}>
              {issue.index ? <strong>{issue.index}: </strong> : null}
              {issue.message}
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  );
}

interface PreflightReportProps {
  result: PreflightResult;
  /** Uploaded analyser file contents, keyed by `analyserKey`. */
  contents: Record<string, string>;
  onContentChange: (key: string, content: string | undefined) => void;
}

/** Blockers, warnings, size summary and one upload slot per analyser file. */
export function PreflightReport({
  result,
  contents,
  onContentChange,
}: PreflightReportProps) {
  return (
    <div className="space-y-4">
      <IssueList
        issues={result.blockers}
        title="Blockers — fix these before importing"
        destructive
      />
      <IssueList issues={result.warnings} title="Warnings" />

      <dl className="grid grid-cols-2 gap-2 text-sm">
        <dt className="text-muted-foreground">Data to copy</dt>
        <dd>{formatBytes(result.staged_bytes)}</dd>
        <dt className="text-muted-foreground">Size once restored</dt>
        <dd>{formatBytes(result.restored_bytes)}</dd>
      </dl>

      {result.analyser_files.length > 0 && (
        <div className="space-y-3">
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-sm font-medium">Analyser files</p>
              <TooltipProvider delayDuration={100}>
                <Tooltip>
                  <TooltipTrigger
                    type="button"
                    aria-label="What is an analyser file?"
                  >
                    <Info className="h-3.5 w-3.5 text-muted-foreground" />
                  </TooltipTrigger>
                  <TooltipContent side="right" className="max-w-xs">
                    OpenSearch analysers decide how text is matched. Some read
                    their rules from a file on the cluster, such as a synonym
                    list (synonyms_path, e.g. “dna, deoxyribonucleic acid”) or a
                    stop-word list (stopwords_path). A snapshot keeps only the
                    path, not the file, so the index cannot open without it.
                    Upload the same file the source cluster used; you can get it
                    from that cluster’s config directory or its owner.
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
            <p className="text-xs text-muted-foreground">
              These indices reference files stored on the source cluster, which
              snapshots do not contain. Upload each file; its lines are inlined
              into the restored index settings.
            </p>
          </div>
          {result.analyser_files.map((ref) => {
            const key = analyserKey(ref);
            const inputId = `analyser-${key.replace(/\W+/g, "-")}`;
            return (
              <div key={key} className="space-y-1">
                <Label htmlFor={inputId}>
                  {`Analyser file for ${ref.index} (${ref.path})`}
                </Label>
                <Input
                  id={inputId}
                  type="file"
                  onChange={async (event) => {
                    const file = event.target.files?.[0];
                    onContentChange(
                      key,
                      file ? await readFileText(file) : undefined,
                    );
                  }}
                />
                <p className="text-xs text-muted-foreground">
                  {contents[key] !== undefined
                    ? "File ready to upload."
                    : `Required for the ${ref.setting} setting.`}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
