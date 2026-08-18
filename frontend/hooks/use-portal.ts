"use client";

import { useEffect, useState } from "react";

/**
 * Returns a stable <div> element appended directly to document.body.
 * Mounting is deferred to the client so SSR never touches the DOM.
 * The element is removed on unmount.
 */
export function usePortal(id: string): HTMLElement | null {
  const [host, setHost] = useState<HTMLElement | null>(null);

  useEffect(() => {
    let el = document.getElementById(id);
    let created = false;
    if (!el) {
      el = document.createElement("div");
      el.id = id;
      document.body.appendChild(el);
      created = true;
    }
    setHost(el);
    return () => {
      if (created && el?.parentNode) {
        el.parentNode.removeChild(el);
      }
    };
  }, [id]);

  return host;
}
