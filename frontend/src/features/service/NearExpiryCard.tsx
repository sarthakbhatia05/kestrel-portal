import { useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { fetchNearExpiry } from "../../api/client";
import type { NearExpiryBasis } from "../../api/types";
import { InfoTooltip } from "../../components/InfoTooltip";
import { SearchInput } from "../../components/SearchInput";
import { useDebouncedValue } from "../../lib/useDebouncedValue";

const percent = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(1)}%`;

const inr = (value: number) =>
  `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

interface Props {
  regionId: number | null;
}

/**
 * Near-expiry is a point-in-time snapshot, not a period range, so it
 * renders its own basis line (snapshot date and threshold) rather than
 * reusing <BasisLine>, which is shaped around period_start/period_end.
 */
function NearExpiryBasisLine({ basis }: { basis: NearExpiryBasis }) {
  return (
    <p className="basis">
      As-at {basis.snapshot_date} &middot; {basis.scope} &middot;{" "}
      {basis.threshold_days}-day threshold &middot;{" "}
      {basis.source_row_count.toLocaleString()} batches
      {basis.damaged_cases > 0 && (
        <>
          {" "}
          &middot; {basis.damaged_cases.toLocaleString()} cases damaged (
          {inr(basis.damaged_value_inr)})
        </>
      )}
      {basis.blocked_cases > 0 && (
        <>
          {" "}
          &middot; {basis.blocked_cases.toLocaleString()} cases blocked (
          {inr(basis.blocked_value_inr)})
        </>
      )}
    </p>
  );
}

export function NearExpiryCard({ regionId }: Props) {
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search, 300);

  const { data, isPending, error } = useQuery({
    queryKey: ["near-expiry", regionId, q],
    queryFn: () =>
      fetchNearExpiry({
        grain: "category",
        regionId,
        ascending: false,
        limit: 5,
        q: q || undefined,
      }),
  });

  if (isPending)
    return (
      <section className="card card--loading">Loading near-expiry stock…</section>
    );
  if (error)
    return (
      <section className="card card--error">
        <h2>Near-expiry stock unavailable</h2>
        <p>{(error as Error).message}</p>
      </section>
    );

  return (
    <section className="card">
      <header className="card__head">
        <div className="card__title">
          <h2>Near-expiry stock</h2>
          <InfoTooltip text="Available stock within the expiry threshold, and the rupee value at risk." />
        </div>
      </header>

      <p className="headline">{percent(data.headline.near_expiry_rate)}</p>

      <dl className="submetrics">
        <div>
          <dt>Near-expiry cases</dt>
          <dd>{data.headline.near_expiry_cases.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Value at risk</dt>
          <dd>{inr(data.headline.near_expiry_value_inr)}</dd>
        </div>
      </dl>

      <NearExpiryBasisLine basis={data.basis} />

      <div className="table-head">
        <h3>{q ? "Matching categories" : "Worst performing categories"}</h3>
        <SearchInput value={search} onChange={setSearch} placeholder="Search categories" />
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Category</th>
              <th scope="col">Near-expiry rate</th>
              <th scope="col">Near-expiry cases</th>
              <th scope="col">Available cases</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.key}>
                <td>{row.label}</td>
                <td>{percent(row.near_expiry_rate)}</td>
                <td>{row.near_expiry_cases.toLocaleString()}</td>
                <td>{row.total_available_cases.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.rows.length === 0 && q && (
        <p className="empty">No categories match &ldquo;{q}&rdquo;.</p>
      )}
    </section>
  );
}
