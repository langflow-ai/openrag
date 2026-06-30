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

import React from "react";
import * as LucideIcons from "lucide-react";

/*
How to use this component:

import Icon from "@site/src/components/icon";

<Icon name="AlertCircle" size={24} color="red" />
*/

type IconProps = {
  name: string;
};

export default function Icon({ name, ...props }: IconProps) {
  const Icon = LucideIcons[name];
  return Icon ? <Icon {...props} /> : null;
}