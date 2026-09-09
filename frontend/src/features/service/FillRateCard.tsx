import { useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { fetchFillRate } from "../../api/client";
import type { Unit } from "../../api/types";
import { BasisLine } from "../../components/BasisLine";
import { InfoTooltip } from "../../components/InfoTooltip";
import { SearchInput } from "../../components/SearchInput";
import { useDebouncedValue } from "../../lib/useDebouncedValue";

const percent = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(1)}%`;

interface Props {
  unit: Unit;
  regionId: number | null;
  period: string;
  onUnitChange: (unit: Unit) => void;
}

export function FillRateCard({ unit, regionId, period, onUnitChange }: Props) {
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search, 300);

  const { data, isPending, error } = useQuery({
    queryKey: ["fill-rate", unit, regionId, period, q],
    queryFn: () =>
      fetchFillRate({
        grain: "outlet",
        unit,
        regionId,
        period,
        ascending: true,
        limit: 5,
        q: q || undefined,
      }),
  });

  if (isPending)
    return <section className="card card--loading">Loading fill rate…</section>;
  if (error)
    return (
      <section className="card card--error">
        <h2>Fill rate unavailable</h2>
        <p>{(error as Error).message}</p>
      </section>
    );

  return (
    <section className="card">
      <header className="card__head">
        <div className="card__title">
          <h2>Fill rate</h2>
          <InfoTooltip text="Delivered units divided by ordered units, in eaches or cases." />
        </div>
        <div className="toggle" role="group" aria-label="Unit of measure">
          {(["eaches", "cases"] as Unit[]).map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={unit === option}
              className={unit === option ? "is-active" : ""}
              onClick={() => onUnitChange(option)}
            >
              {option}
            </button>
          ))}
        </div>
      </header>

      <p className="headline">{percent(data.headline)}</p>

      <dl className="submetrics">
        <div>
          <dt>Delivered</dt>
          <dd>{Math.round(data.numerator).toLocaleString()}</dd>
        </div>
        <div>
          <dt>Ordered</dt>
          <dd>{Math.round(data.denominator).toLocaleString()}</dd>
        </div>
      </dl>

      <BasisLine basis={data.basis} />

      <div className="table-head">
        <h3>{q ? "Matching outlets" : "Worst performing outlets"}</h3>
        <SearchInput value={search} onChange={setSearch} placeholder="Search outlets" />
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Outlet</th>
              <th scope="col">Fill rate</th>
              <th scope="col">Delivered</th>
              <th scope="col">Ordered</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.key}>
                <td>{row.label}</td>
                <td>{percent(row.value)}</td>
                <td>{Math.round(row.numerator).toLocaleString()}</td>
                <td>{Math.round(row.denominator).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.rows.length === 0 && q && (
        <p className="empty">No outlets match &ldquo;{q}&rdquo;.</p>
      )}
    </section>
  );
}
