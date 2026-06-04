"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useAuth } from "@/contexts/auth-context";
import {
  BRAND_COOKIE,
  type Brand,
  IBM_THEME_DEV,
  isCloudBrand,
} from "@/lib/brand";

export type { Brand } from "@/lib/brand";
export { IBM_THEME_DEV } from "@/lib/brand";

const BRAND_COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

function persistBrandPreference(brand: Brand) {
  localStorage.setItem("brand", brand);
  document.cookie = `${BRAND_COOKIE}=${brand}; path=/; max-age=${BRAND_COOKIE_MAX_AGE}; SameSite=Lax`;
}

interface BrandContextValue {
  brand: Brand;
  setBrand: (brand: Brand) => void;
}

const BrandContext = createContext<BrandContextValue>({
  brand: "oss",
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
  const [brand, setBrandState] = useState<Brand>("oss");
  const { isIbmAuthMode } = useAuth();

  useEffect(() => {
    if (isIbmAuthMode) {
      applyBrand("ibm");
      setBrandState("ibm");
    } else {
      const stored =
        (localStorage.getItem("brand") as Brand) ??
        (IBM_THEME_DEV ? "ibm" : "oss");
      persistBrandPreference(stored);
      applyBrand(stored);
      setBrandState(stored);
    }
  }, [isIbmAuthMode]);

  function setBrand(newBrand: Brand) {
    persistBrandPreference(newBrand);
    applyBrand(newBrand);
    setBrandState(newBrand);
  }

  return (
    <BrandContext.Provider value={{ brand, setBrand }}>
      {children}
    </BrandContext.Provider>
  );
}

export const useBrand = () => useContext(BrandContext);

export const useIsCloudBrand = () => {
  const { brand } = useContext(BrandContext);
  const { isIbmAuthMode } = useAuth();
  return isCloudBrand({ isIbmAuthMode, brand });
};
