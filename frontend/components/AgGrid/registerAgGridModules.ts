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

import {
  CellStyleModule,
  ClientSideRowModelModule,
  ColumnApiModule,
  ColumnAutoSizeModule,
  DateFilterModule,
  EventApiModule,
  GridStateModule,
  ModuleRegistry,
  PaginationModule,
  QuickFilterModule,
  RowApiModule,
  RowSelectionModule,
  TextFilterModule,
  ValidationModule,
} from "ag-grid-community";

// Importing necessary modules from ag-grid-community
// https://www.ag-grid.com/javascript-data-grid/modules/#selecting-modules

ModuleRegistry.registerModules([
  ColumnAutoSizeModule,
  ColumnApiModule,
  PaginationModule,
  CellStyleModule,
  QuickFilterModule,
  ClientSideRowModelModule,
  TextFilterModule,
  DateFilterModule,
  EventApiModule,
  GridStateModule,
  RowApiModule,
  RowSelectionModule,
  // The ValidationModule adds helpful console warnings/errors that can help identify bad configuration during development.
  ...(process.env.NODE_ENV !== "production" ? [ValidationModule] : []),
]);
