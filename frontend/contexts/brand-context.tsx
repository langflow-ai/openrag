"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useAuth } from "@/contexts/auth-context";

export type Brand = "oss" | "ibm";

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
      const stored = (localStorage.getItem("brand") as Brand) ?? "oss";
      applyBrand(stored);
      setBrandState(stored);
    }
  }, [isIbmAuthMode]);

  function setBrand(newBrand: Brand) {
    localStorage.setItem("brand", newBrand);
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

export const useIsCloudBrand = () => useContext(BrandContext).brand === "ibm";
