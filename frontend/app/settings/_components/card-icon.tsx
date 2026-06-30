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

import { cn } from "@/lib/utils";

interface CardIconProps {
  isActive: boolean;
  activeBgColor: string;
  children: React.ReactNode;
}

export default function CardIcon({
  isActive,
  activeBgColor,
  children,
}: CardIconProps) {
  return (
    <div
      className={cn(
        "w-8 h-8 rounded flex items-center justify-center border",
        isActive
          ? `${activeBgColor} text-black`
          : "bg-muted grayscale group-hover:bg-background",
      )}
    >
      {children}
    </div>
  );
}
