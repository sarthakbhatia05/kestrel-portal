import { useQuery } from "@tanstack/react-query";

import { fetchScope } from "../../api/client";

interface Props {
  regionId: number | null;
  period: string;
  onRegionChange: (id: number | null) => void;
  onPeriodChange: (period: string) => void;
}

/**
 * Region and period selectors (C5.3: one scope, applied everywhere).
 *
 * Both option lists come from the server, which derives periods from the
 * order dates actually present — so nothing offered here can produce an
 * empty dashboard. While the options are loading the bar renders the
 * current scope as text rather than an empty select, because a control
 * that appears with no choices in it reads as broken.
 */
export function ScopeBar({ regionId, period, onRegionChange, onPeriodChange }: Props) {
  const scope = useQuery({ queryKey: ["scope"], queryFn: fetchScope });

  const regions = scope.data?.regions ?? [];
  const periods = scope.data?.periods ?? [];
  const quarters = periods.filter((option) => option.kind === "quarter");
  const months = periods.filter((option) => option.kind === "month");

  const regionName = regions.find((r) => r.region_id === regionId)?.region_name;
  const periodLabel = periods.find((p) => p.value === period)?.label;

  if (scope.isPending || scope.isError)
    return (
      <span className="topbar__scope">
        {regionId === null ? "All regions" : `Region ${regionId}`} &middot;{" "}
        {period === "latest" ? "Latest period" : period}
      </span>
    );

  return (
    <div className="scopebar">
      <label className="scopebar__field">
        <span className="scopebar__label">Region</span>
        <select
          value={regionId === null ? "" : String(regionId)}
          onChange={(event) =>
            onRegionChange(event.target.value === "" ? null : Number(event.target.value))
          }
        >
          <option value="">All regions</option>
          {regions.map((region) => (
            <option key={region.region_id} value={region.region_id}>
              {region.region_name}
            </option>
          ))}
        </select>
      </label>

      <label className="scopebar__field">
        <span className="scopebar__label">Period</span>
        <select value={period} onChange={(event) => onPeriodChange(event.target.value)}>
          <option value="latest">Latest complete quarter</option>
          {quarters.length > 0 && (
            <optgroup label="Quarters">
              {quarters.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </optgroup>
          )}
          {months.length > 0 && (
            <optgroup label="Months">
              {months.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </optgroup>
          )}
          {/* A period typed into a question (a week, an explicit range) is
              a legitimate scope the dropdown does not enumerate. Show it
              rather than silently falling back to the first option. */}
          {periodLabel === undefined && period !== "latest" && (
            <option value={period}>{period}</option>
          )}
        </select>
      </label>

      <span className="scopebar__reading">
        {regionName ?? "All regions"} &middot; {periodLabel ?? period}
      </span>
    </div>
  );
}
