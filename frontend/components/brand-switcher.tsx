"use client";

import { useBrand } from "@/contexts/brand-context";

export function BrandSwitcher() {
  const { brand, setBrand } = useBrand();

  return (
    <div className="flex items-center border border-border rounded-full">
      <button
        type="button"
        className={`px-3 h-6 rounded-full text-xs font-medium transition-colors ${
          brand === "oss"
            ? "bg-foreground text-background"
            : "text-foreground hover:bg-foreground hover:text-background"
        }`}
        onClick={() => setBrand("oss")}
        data-testid="brand_oss_button"
        id="brand_oss_button"
      >
        OSS
      </button>
      <button
        type="button"
        className={`px-3 h-6 rounded-full text-xs font-medium transition-colors ${
          brand === "ibm"
            ? "bg-blue-600 text-white"
            : "text-foreground hover:bg-blue-600 hover:text-white"
        }`}
        onClick={() => setBrand("ibm")}
        data-testid="brand_ibm_button"
        id="brand_ibm_button"
      >
        IBM
      </button>
    </div>
  );
}

export default BrandSwitcher;
