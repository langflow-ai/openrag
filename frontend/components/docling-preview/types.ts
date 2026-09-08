/** Lit lifecycle bits exposed by @docling/docling-components elements. */
export type LitUpdatable = {
  updateComplete?: Promise<boolean>;
  requestUpdate?: () => void;
};

export type DoclingImgElement = HTMLElement &
  LitUpdatable & {
    src?: Record<string, unknown> | string;
    items?: string | unknown[];
    trim?: string;
    itemStyle?: (page: unknown, item: unknown) => string;
    itemPart?: (page: unknown, item: unknown) => string;
  };

export type DoclingImgPageElement = HTMLElement &
  LitUpdatable & {
    page?: { page_no?: number };
    itemStyle?: (page: unknown, item: unknown) => string;
    itemPart?: (page: unknown, item: unknown) => string;
  };

export type OverlayBox = {
  top: number;
  left: number;
  width: number;
  height: number;
};

export type DoclingTextItem = {
  text?: string;
  label?: string;
  level?: number;
};

export type DoclingTableCell = { text?: string };

export type DoclingTableItem = {
  data?: { grid?: DoclingTableCell[][] };
};

export type DoclingPictureItem = {
  image?: { uri?: string };
  captions?: unknown[];
};

export type DoclingRef = { $ref?: string; cref?: string };

export type ParsedItem =
  | { kind: "text"; id: string; node: DoclingTextItem }
  | { kind: "table"; id: string; node: DoclingTableItem }
  | { kind: "picture"; id: string; node: DoclingPictureItem };

export type PreviewGroup =
  | { kind: "chunk"; items: ParsedItem[] }
  | { kind: "plain"; item: ParsedItem };
