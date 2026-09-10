import { useCallback, useEffect, useState } from "react";

import type { Unit } from "../api/types";

/**
 * Scope, unit and period live in the URL.
 *
 * One source of truth is what makes C5.3 hold — the selected scope applies
 * to every surface, including ask-anything — and it makes any view
 * shareable by pasting the address.
 */
export function useScope() {
  const [params, setParams] = useState(
    () => new URLSearchParams(window.location.search),
  );

  useEffect(() => {
    const onPop = () => setParams(new URLSearchParams(window.location.search));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const update = useCallback((key: string, value: string | null) => {
    const next = new URLSearchParams(window.location.search);
    if (value === null) next.delete(key);
    else next.set(key, value);
    window.history.pushState({}, "", `?${next}`);
    setParams(next);
  }, []);

  const regionParam = params.get("region");

  return {
    unit: (params.get("unit") as Unit) ?? "eaches",
    regionId: regionParam ? Number(regionParam) : null,
    period: params.get("period") ?? "latest",
    setUnit: (unit: Unit) => update("unit", unit),
    setRegionId: (id: number | null) => update("region", id === null ? null : String(id)),
    // "latest" is the default, so it is dropped from the URL rather than
    // written into it: a shared link carries only what was actually chosen.
    setPeriod: (period: string) => update("period", period === "latest" ? null : period),
  };
}
