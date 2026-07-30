import {
  Archive,
  Bolt,
  Book,
  Cable,
  Database,
  FileImage,
  Filter,
  Folder,
  Gem,
  Ghost,
  Globe,
  Hammer,
  HardDrive,
  Layers3,
  Library,
  Map as MapIcon,
  MessagesSquare,
  Scroll,
  Shield,
  ShoppingBag,
  ShoppingCart,
  SquareStack,
  Swords,
  Upload,
} from "lucide-react";
import type { SVGProps } from "react";

export const FILTER_COLORS = [
  "zinc",
  "pink",
  "purple",
  "indigo",
  "emerald",
  "amber",
  "red",
] as const;
export type FilterColor = (typeof FILTER_COLORS)[number];

export const ICON_MAP = {
  filter: Filter,
  book: Book,
  scroll: Scroll,
  library: Library,
  map: MapIcon,
  image: FileImage,
  layers3: Layers3,
  database: Database,
  folder: Folder,
  archive: Archive,
  messagesSquare: MessagesSquare,
  squareStack: SquareStack,
  ghost: Ghost,
  gem: Gem,
  swords: Swords,
  bolt: Bolt,
  shield: Shield,
  hammer: Hammer,
  globe: Globe,
  hardDrive: HardDrive,
  upload: Upload,
  cable: Cable,
  shoppingCart: ShoppingCart,
  shoppingBag: ShoppingBag,
} as const;

export type IconKey = keyof typeof ICON_MAP;

export function iconKeyToComponent(
  key?: string,
): React.ComponentType<SVGProps<SVGSVGElement>> | undefined {
  if (!key) return undefined;
  return (
    ICON_MAP as Record<string, React.ComponentType<SVGProps<SVGSVGElement>>>
  )[key];
}
