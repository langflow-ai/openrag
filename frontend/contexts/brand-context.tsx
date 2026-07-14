"use client";

import {
  createContext,
  use,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useAuth } from "@/contexts/auth-context";
import {
  type Brand,
  DEFAULT_BRAND,
  isCloudBrand,
  resolveBrand,
} from "@/lib/brand";

export type { Brand } from "@/lib/brand";
export { IBM_THEME_DEV } from "@/lib/brand";

interface BrandContextValue {
  brand: Brand;
  setBrand: (brand: Brand) => void;
}

const BrandContext = createContext<BrandContextValue>({
  brand: DEFAULT_BRAND,
  setBrand: () => {},
});

function applyBrand(brand: Brand) {
  if (brand === "ibm") {
    document.documentElement.setAttribute("data-theme", "ibm");
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
}

export function BrandProvider({ children }: { children: React.ReactNode }) {
  const [storedBrand, setStoredBrandState] = useState<Brand>(DEFAULT_BRAND);
  const { isIbmAuthMode } = useAuth();
  // IBM auth always presents as IBM in context; dev OSS/IBM toggle uses localStorage.
  const brand: Brand = isIbmAuthMode ? "ibm" : storedBrand;

  useEffect(() => {
    if (!isIbmAuthMode) {
      const stored = resolveBrand(localStorage.getItem("brand") ?? undefined);
      localStorage.setItem("brand", stored);
      setStoredBrandState(stored);
    }
  }, [isIbmAuthMode]);

  useEffect(() => {
    applyBrand(brand);
  }, [brand]);

  const setBrand = useCallback(
    (newBrand: Brand) => {
      if (isIbmAuthMode) return;
      localStorage.setItem("brand", newBrand);
      setStoredBrandState(newBrand);
    },
    [isIbmAuthMode],
  );

  const value = useMemo(() => ({ brand, setBrand }), [brand, setBrand]);

  return (
    <BrandContext.Provider value={value}>{children}</BrandContext.Provider>
  );
}

export const useBrand = () => use(BrandContext);

export const useIsCloudBrand = () => {
  const { brand } = use(BrandContext);
  return isCloudBrand(brand);
};
