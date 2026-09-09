import type { MetricBasis } from "../api/types";

/**
 * Every figure renders the basis it was derived from.
 *
 * This is the whole point of the product: a number without its basis is
 * the contested number the control tower exists to replace.
 */
export function BasisLine({
  basis,
  rowNoun = "order lines",
}: {
  basis: MetricBasis;
  rowNoun?: string;
}) {
  return (
    <p className="basis">
      {basis.period_label} ({basis.period_start} to {basis.period_end}) &middot;{" "}
      {basis.scope} &middot; {basis.unit} &middot;{" "}
      {basis.source_row_count.toLocaleString()} {rowNoun}
      {basis.exclusions_applied.length > 0 && (
        <> &middot; excludes {basis.exclusions_applied.join(", ")}</>
      )}
      {basis.tolerance_minutes != null && (
        <> &middot; {basis.tolerance_minutes} min tolerance</>
      )}
      {basis.unmeasured_count > 0 && (
        <> &middot; {basis.unmeasured_count.toLocaleString()} unmeasured</>
      )}
    </p>
  );
}
