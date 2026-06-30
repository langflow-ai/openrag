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

import AnimatedProcessingIcon from "../icons/animated-processing-icon";

export type Status =
  | "processing"
  | "active"
  | "unavailable"
  | "hidden"
  | "sync"
  | "failed";

interface StatusBadgeProps {
  status: Status;
  className?: string;
}

const statusConfig = {
  processing: {
    label: "Processing",
    className: "text-muted-foreground ",
  },
  active: {
    label: "Active",
    className: "text-accent-emerald-foreground ",
  },
  unavailable: {
    label: "Unavailable",
    className: "text-accent-red-foreground ",
  },
  failed: {
    label: "Failed",
    className: "text-accent-red-foreground ",
  },
  hidden: {
    label: "Hidden",
    className: "text-muted-foreground ",
  },
  sync: {
    label: "Sync",
    className: "text-accent-amber-foreground underline",
  },
};

export const StatusBadge = ({ status, className }: StatusBadgeProps) => {
  const config = statusConfig[status];

  return (
    <div
      className={`inline-flex items-center gap-1 ${config.className} ${
        className || ""
      }`}
    >
      {status === "processing" && (
        <AnimatedProcessingIcon className="text-current shrink-0" />
      )}
      {config.label}
    </div>
  );
};
