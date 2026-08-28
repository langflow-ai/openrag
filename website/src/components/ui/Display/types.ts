// Types
import { Breakpoint } from "@/lib/types/definitions";

/**
 * The available sizes.
 */
export type Size = 10 | 20 | 30 | 100 | 150 | 200 | 300 | 400 | 500 | 600 | 700;

/**
 * The available weights.
 */
export enum Weight {
  Bold = 700,
  Semibold = 600,
  Medium = 500,
  Regular = 400,
  Light = 300,
}

export type SizeRecord = { [key in Breakpoint]?: Size };
