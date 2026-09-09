import { useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { fetchExcursions } from "../../api/client";
import type { ExcursionsBasis } from "../../api/types";
import { InfoTooltip } from "../../components/InfoTooltip";
import { SearchInput } from "../../components/SearchInput";
import { useDebouncedValue } from "../../lib/useDebouncedValue";

const percent = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(2)}%`;

interface Props {
  regionId: number | null;
  period: string;
}

/**
 * Excursions has no eaches/cases toggle and no unmeasured-count concept
 * (the breach flag is never null), so it renders its own basis line rather
 * than reusing <BasisLine>, the same way returns and near-expiry do.
 */
function ExcursionsBasisLine({ basis }: { basis: ExcursionsBasis }) {
  return (
    <p className="basis">
      {basis.period_label} ({basis.period_start} to {basis.period_end}) &middot;{" "}
      {basis.scope} &middot; {basis.source_row_count.toLocaleString()} chilled deliveries
      {basis.exclusions_applied.length > 0 && (
        <> &middot; excludes {basis.exclusions_applied.join(", ")}</>
      )}
    </p>
  );
}

export function ExcursionsCard({ regionId, period }: Props) {
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search, 300);

  const { data, isPending, error } = useQuery({
    queryKey: ["excursions", regionId, period, q],
    queryFn: () =>
      fetchExcursions({
        grain: "route",
        regionId,
        period,
        ascending: false,
        limit: 5,
        q: q || undefined,
      }),
  });

  if (isPending)
    return <section className="card card--loading">Loading excursions…</section>;
  if (error)
    return (
      <section className="card card--error">
        <h2>Excursions unavailable</h2>
        <p>{(error as Error).message}</p>
      </section>
    );

  return (
    <section className="card">
      <header className="card__head">
        <div className="card__title">
          <h2>Temperature excursions</h2>
          <InfoTooltip text="Chilled deliveries whose reefer breached its temperature band in transit, per hundred chilled deliveries." />
        </div>
      </header>

      <p className="headline">{percent(data.headline.excursion_rate)}</p>

      <dl className="submetrics">
        <div>
          <dt>Chilled deliveries</dt>
          <dd>{data.headline.chilled_count.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Breached</dt>
          <dd>{data.headline.excursion_count.toLocaleString()}</dd>
        </div>
      </dl>

      <ExcursionsBasisLine basis={data.basis} />

      <div className="table-head">
        <h3>{q ? "Matching routes" : "Worst concentration by route"}</h3>
        <SearchInput value={search} onChange={setSearch} placeholder="Search routes" />
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Route</th>
              <th scope="col">Excursion rate</th>
              <th scope="col">Breached</th>
              <th scope="col">Chilled deliveries</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.key}>
                <td>{row.label}</td>
                <td>{percent(row.excursion_rate)}</td>
                <td>{row.excursion_count.toLocaleString()}</td>
                <td>{row.chilled_count.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.rows.length === 0 && q && (
        <p className="empty">No routes match &ldquo;{q}&rdquo;.</p>
      )}
    </section>
  );
}
