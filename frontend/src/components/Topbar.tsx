import type { MouseEvent } from "react";

import { ScopeBar } from "../features/landing/ScopeBar";
import type { View } from "../lib/scope";

interface Props {
  view: View;
  viewHref: (view: View) => string;
  onViewChange: (view: View) => void;
  regionId: number | null;
  period: string;
  onRegionChange: (id: number | null) => void;
  onPeriodChange: (period: string) => void;
}

const VIEWS: { view: View; label: string }[] = [
  { view: "tower", label: "Control tower" },
  { view: "quality", label: "Data quality" },
];

/**
 * Shared by every view, so the scope selectors stay put when the view
 * changes and the selected scope carries across (C5.3).
 *
 * The view links are real links — they open in a new tab and can be
 * copied — and only a plain click is intercepted to switch in place.
 */
export function Topbar({ view, viewHref, onViewChange, ...scope }: Props) {
  const navigate = (target: View) => (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
    event.preventDefault();
    onViewChange(target);
  };

  return (
    <div className="topbar">
      <div className="topbar__left">
        <span className="topbar__mark">Kestrel</span>
        <nav className="topnav" aria-label="Views">
          {VIEWS.map((item) => (
            <a
              key={item.view}
              href={viewHref(item.view)}
              className={`topnav__link${item.view === view ? " is-active" : ""}`}
              aria-current={item.view === view ? "page" : undefined}
              onClick={navigate(item.view)}
            >
              {item.label}
            </a>
          ))}
        </nav>
      </div>
      <ScopeBar {...scope} />
    </div>
  );
}
