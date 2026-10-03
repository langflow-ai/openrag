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
  RowStyleModule,
  TextFilterModule,
  ValidationModule,
} from "ag-grid-community";

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
  RowStyleModule,
  // Adds dev-only console warnings for bad configuration.
  ...(process.env.NODE_ENV !== "production" ? [ValidationModule] : []),
]);
