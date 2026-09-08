import { useQuery } from "@tanstack/react-query";

import { fetchFillRate } from "../../api/client";
import type { Unit } from "../../api/types";
import { BasisLine } from "../../components/BasisLine";

const percent = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(1)}%`;

interface Props {
  unit: Unit;
  regionId: number | null;
  period: string;
  onUnitChange: (unit: Unit) => void;
}

export function FillRateCard({ unit, regionId, period, onUnitChange }: Props) {
  const { data, isPending, error } = useQuery({
    queryKey: ["fill-rate", unit, regionId, period],
    queryFn: () =>
      fetchFillRate({
        grain: "outlet",
        unit,
        regionId,
        period,
        ascending: true,
        limit: 5,
      }),
  });

  if (isPending) return <section className="card">Loading fill rate…</section>;
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
        <h2>Fill rate</h2>
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
      <BasisLine basis={data.basis} />

      <h3>Worst performing outlets</h3>
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
    </section>
  );
}
