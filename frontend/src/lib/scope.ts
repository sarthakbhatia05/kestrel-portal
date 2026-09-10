import { useCallback, useEffect, useState } from "react";

import type { Unit } from "../api/types";

/** Which screen is showing. "tower" is the default and is kept out of the URL. */
export type View = "tower" | "quality";

/**
 * Scope, unit, period and view live in the URL.
 *
 * One source of truth is what makes C5.3 hold — the selected scope applies
 * to every surface, including ask-anything and the quality view — and it
 * makes any view shareable by pasting the address. Call this once, at the
 * top: two instances would each hold their own copy and drift apart, since
 * pushState notifies nobody.
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
  const view: View = params.get("view") === "quality" ? "quality" : "tower";

  return {
    unit: (params.get("unit") as Unit) ?? "eaches",
    regionId: regionParam ? Number(regionParam) : null,
    period: params.get("period") ?? "latest",
    view,
    setUnit: (unit: Unit) => update("unit", unit),
    setRegionId: (id: number | null) => update("region", id === null ? null : String(id)),
    // "latest" is the default, so it is dropped from the URL rather than
    // written into it: a shared link carries only what was actually chosen.
    setPeriod: (period: string) => update("period", period === "latest" ? null : period),
    setView: (next: View) => {
      update("view", next === "tower" ? null : next);
      window.scrollTo(0, 0);
    },
    /** The address of another view with the current scope carried over. */
    viewHref: (target: View) => {
      const next = new URLSearchParams(params);
      if (target === "tower") next.delete("view");
      else next.set("view", target);
      return `?${next}`;
    },
  };
}
