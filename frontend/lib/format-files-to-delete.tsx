/* ******************************************************************************
 * IBM Confidential
 *
 * OCO Source Materials
 *
 *  Copyright IBM Corp. 2026  All Rights Reserved.
 *
 * The source code for this program is not published or otherwise divested
 * of its trade secrets, irrespective of what has been deposited with
 * the U.S. Copyright Office.
 ****************************************************************************** */

import { type ReactNode } from "react";

export function formatFilesToDelete(
  files: Array<{ filename: string }>,
  maxVisible = 5,
): ReactNode {
  const visibleFiles = files.slice(0, maxVisible);
  const remainingCount = files.length - maxVisible;
  return (
    <ul className="list-disc pl-5">
      {visibleFiles.map((file) => (
        <li key={file.filename} className="my-2" title={file.filename}>
          <p className="overflow-hidden text-ellipsis whitespace-nowrap max-w-[200px]">
            {file.filename}
          </p>
        </li>
      ))}
      {remainingCount > 0 ? (
        <li>
          &hellip; and {remainingCount} more document
          {remainingCount > 1 ? "s" : ""}
        </li>
      ) : (
        ""
      )}
    </ul>
  );
}
