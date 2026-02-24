import { type ReactNode } from "react";

export function formatFilesToDelete(
  files: Array<{ filename: string }>,
  maxVisible = 5,
): ReactNode {
  const visibleFiles = files.slice(0, maxVisible);
  const remainingCount = files.length - maxVisible;
  return (
    <ul className="list-disc list-inside max-w-[29rem] sm:max-w-[calc(425px-3rem)]">
      {visibleFiles.map((file) => <li key={file.filename} className="my-2 truncate">{file.filename}</li>)}
      {remainingCount > 0 ? <li>&hellip; and {remainingCount} more document{
        remainingCount > 1 ? "s" : ""
      }</li> : "" }
    </ul>
  );
}
