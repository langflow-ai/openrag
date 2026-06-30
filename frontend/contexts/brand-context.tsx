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

"use client";

import { createContext, useContext, useEffect, useState } from "react";
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

  function setBrand(newBrand: Brand) {
    if (isIbmAuthMode) return;
    localStorage.setItem("brand", newBrand);
    setStoredBrandState(newBrand);
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
  return isCloudBrand(brand);
};
