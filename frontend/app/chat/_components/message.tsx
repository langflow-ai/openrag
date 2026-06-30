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

import { ReactNode } from "react";

interface MessageProps {
  icon: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
}

export function Message({ icon, children, actions }: MessageProps) {
  return (
    <div className="flex gap-3">
      {icon}
      <div className="flex-1 min-w-0">{children}</div>
      {actions && <div className="flex-shrink-0 ml-2">{actions}</div>}
    </div>
  );
}
