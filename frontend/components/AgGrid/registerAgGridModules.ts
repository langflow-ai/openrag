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
  RowSelectionModule,
  // The ValidationModule adds helpful console warnings/errors that can help identify bad configuration during development.
  ...(process.env.NODE_ENV !== "production" ? [ValidationModule] : []),
]);
