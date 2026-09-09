import { useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { fetchReturns } from "../../api/client";
import type { ReturnsBasis } from "../../api/types";
import { InfoTooltip } from "../../components/InfoTooltip";
import { SearchInput } from "../../components/SearchInput";
import { useDebouncedValue } from "../../lib/useDebouncedValue";

const percent = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(2)}%`;

const inr = (value: number) =>
  `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

interface Props {
  regionId: number | null;
  period: string;
}

/**
 * Returns has no eaches/cases toggle and reports pending/rejected value
 * instead of an unmeasured count, so it renders its own basis line rather
 * than reusing <BasisLine>, which is shaped around the other two metrics.
 */
function ReturnsBasisLine({ basis }: { basis: ReturnsBasis }) {
  return (
    <p className="basis">
      {basis.period_label} ({basis.period_start} to {basis.period_end}) &middot;{" "}
      {basis.scope} &middot; {basis.source_row_count.toLocaleString()} credit notes
      {basis.exclusions_applied.length > 0 && (
        <> &middot; excludes {basis.exclusions_applied.join(", ")}</>
      )}
      {basis.pending_count > 0 && (
        <>
          {" "}
          &middot; {basis.pending_count.toLocaleString()} pending ({inr(basis.pending_value_inr)})
        </>
      )}
      {basis.rejected_count > 0 && (
        <>
          {" "}
          &middot; {basis.rejected_count.toLocaleString()} rejected ({inr(basis.rejected_value_inr)})
        </>
      )}
    </p>
  );
}

export function ReturnsCard({ regionId, period }: Props) {
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search, 300);

  const { data, isPending, error } = useQuery({
    queryKey: ["returns", regionId, period, q],
    queryFn: () =>
      fetchReturns({
        grain: "category",
        regionId,
        period,
        ascending: false,
        limit: 5,
        q: q || undefined,
      }),
  });

  if (isPending)
    return <section className="card card--loading">Loading returns…</section>;
  if (error)
    return (
      <section className="card card--error">
        <h2>Returns unavailable</h2>
        <p>{(error as Error).message}</p>
      </section>
    );

  return (
    <section className="card">
      <header className="card__head">
        <div className="card__title">
          <h2>Returns and credit note leakage</h2>
          <InfoTooltip text="Value credited back on approved returns, as a share of what was dispatched." />
        </div>
      </header>

      <p className="headline">{percent(data.headline.returns_rate)}</p>

      <dl className="submetrics">
        <div>
          <dt>Credit notes (approved)</dt>
          <dd>{inr(data.headline.credit_note_value_inr)}</dd>
        </div>
        <div>
          <dt>Cold-chain-attributable</dt>
          <dd>{percent(data.headline.cold_chain_rate)}</dd>
        </div>
      </dl>

      <ReturnsBasisLine basis={data.basis} />

      <div className="table-head">
        <h3>{q ? "Matching categories" : "Worst performing categories"}</h3>
        <SearchInput value={search} onChange={setSearch} placeholder="Search categories" />
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Category</th>
              <th scope="col">Returns rate</th>
              <th scope="col">Credit notes</th>
              <th scope="col">Dispatch value</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.key}>
                <td>{row.label}</td>
                <td>{percent(row.returns_rate)}</td>
                <td>{inr(row.credit_note_value_inr)}</td>
                <td>{inr(row.dispatch_value_inr)}</td>
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
