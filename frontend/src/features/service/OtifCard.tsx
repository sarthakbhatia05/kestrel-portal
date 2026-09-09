import { useQuery } from "@tanstack/react-query";

import { fetchOtif } from "../../api/client";
import { BasisLine } from "../../components/BasisLine";

const percent = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(1)}%`;

interface Props {
  regionId: number | null;
  period: string;
}

export function OtifCard({ regionId, period }: Props) {
  const { data, isPending, error } = useQuery({
    queryKey: ["otif", regionId, period],
    queryFn: () =>
      fetchOtif({
        grain: "outlet",
        regionId,
        period,
        ascending: true,
        limit: 5,
      }),
  });

  if (isPending) return <section className="card">Loading OTIF…</section>;
  if (error)
    return (
      <section className="card card--error">
        <h2>OTIF unavailable</h2>
        <p>{(error as Error).message}</p>
      </section>
    );

  return (
    <section className="card">
      <header className="card__head">
        <h2>On-time in-full</h2>
      </header>

      <p className="headline">{percent(data.headline.otif)}</p>

      <dl className="submetrics">
        <div>
          <dt>On time</dt>
          <dd>{percent(data.headline.on_time_rate)}</dd>
        </div>
        <div>
          <dt>In full</dt>
          <dd>{percent(data.headline.in_full_rate)}</dd>
        </div>
      </dl>

      <BasisLine basis={data.basis} rowNoun="deliveries" />

      <h3>Worst performing outlets</h3>
      <table>
        <thead>
          <tr>
            <th scope="col">Outlet</th>
            <th scope="col">OTIF</th>
            <th scope="col">On time</th>
            <th scope="col">In full</th>
            <th scope="col">Due</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.key}>
              <td>{row.label}</td>
              <td>{percent(row.otif)}</td>
              <td>{percent(row.on_time_rate)}</td>
              <td>{percent(row.in_full_rate)}</td>
              <td>{row.due_count.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
