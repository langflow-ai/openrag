// Dependencies
import { UrlObject } from "url";

/**
 * TypeScript definitions
 * Use this definitions file to create Global TypeScript Definitions
 * that can be used on any part of the project.
 *
 */
export type Json =
  | string
  | number
  | boolean
  | { [property: string]: any }
  | Json[]
  | any;

export type CSSModule = {
  [key: string]: string;
};

export type ImageLayout = "intrinsic" | "fixed" | "responsive" | "fill";

export type ImageLoading = "lazy" | "eager";

export type ImagePlaceholder = "blur" | "empty";

export type Vertical = "astra" | "luna" | "enterprise" | "ds";

export type Position = "center" | "left" | "right";

export type ColSize = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12;

export type ClassNameHash = {
  [index: string]: boolean;
};

export declare type Url = string | UrlObject;

export enum Breakpoint {
  XS = "xs",
  SM = "sm",
  MD = "md",
  LG = "lg",
  XL = "xl",
  XXL = "xxl",
}
