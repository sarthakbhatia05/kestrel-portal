import { useState } from "react";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { fetchLedger, fetchQuality } from "../../api/client";
import type { MeasureExclusions, RuleSummary } from "../../api/types";

const EXCLUSION_RULES = ["X1", "X2", "X3", "X4", "X5"];
const LEDGER_PAGE = 50;

const count = (value: number) => value.toLocaleString();
const share = (part: number, whole: number) =>
  whole === 0 ? "—" : `${((part / whole) * 100).toFixed(1)}%`;

interface Props {
  regionId: number | null;
  period: string;
}

/**
 * The quality ledger as a product surface (PRD 6.4): what the figures on
 * the control tower leave out, in counts, for the scope being viewed.
 *
 * Counts are per record the figures are built from (order lines,
 * deliveries, credit notes) rather than per ledger entry, because one
 * soft-deleted outlet is one ledger entry but thousands of excluded lines.
 */
export function QualityView({ regionId, period }: Props) {
  const [selected, setSelected] = useState<RuleSummary | null>(null);

  const { data, isPending, error } = useQuery({
    queryKey: ["quality", regionId, period],
    queryFn: () => fetchQuality({ regionId, period }),
  });

  return (
    <main className="page">
      <header className="page__head">
        <h1>Data quality</h1>
        <p>
          What the figures on the control tower leave out, and why. Excluded records are
          flagged and counted, never deleted.
        </p>
      </header>

      {isPending && <section className="card card--loading">Loading data quality…</section>}
      {error && (
        <section className="card card--error">
          <h2>Data quality unavailable</h2>
          <p>{(error as Error).message}</p>
        </section>
      )}

      {data && (
        <div className="quality">
          <section className="card">
            <header className="card__head">
              <h2>Excluded from this view</h2>
            </header>
            <Lead measure={data.measures[0]} scope={data.scope} period={data.period_label} />
            <p className="basis">
              {data.period_label} ({data.period_start} to {data.period_end}) &middot;{" "}
              {data.scope}
            </p>
            <ExclusionsTable measures={data.measures} rules={data.rules} />
            <ul className="quality__notes">
              <li>
                A record can be excluded by more than one rule, so the rule columns can add up
                to more than the excluded total.
              </li>
              {data.measures
                .filter((measure) => measure.note)
                .map((measure) => (
                  <li key={measure.measure}>
                    {measure.label}: {measure.note}
                  </li>
                ))}
            </ul>
          </section>

          <section className="card">
            <header className="card__head">
              <h2>Rules</h2>
            </header>
            <p className="basis">
              Ledger entries are for the whole build, not the selected scope
              {data.built_at && <> &middot; built {new Date(data.built_at).toLocaleString()}</>}
            </p>
            <RulesTable
              rules={data.rules}
              selected={selected?.rule_ref ?? null}
              onSelect={setSelected}
            />
            {selected && (
              <LedgerPanel
                key={selected.rule_ref}
                rule={selected}
                onClose={() => setSelected(null)}
              />
            )}
          </section>
        </div>
      )}
    </main>
  );
}

/** The one sentence Divya reads: how much of the headline service figure is set aside. */
function Lead({
  measure,
  scope,
  period,
}: {
  measure: MeasureExclusions;
  scope: string;
  period: string;
}) {
  if (measure.in_scope_count === null || measure.excluded_count === null) return null;
  if (measure.in_scope_count === 0)
    return <p className="quality__lead">No {measure.entity} fall in this scope.</p>;

  return (
    <p className="quality__lead">
      {scope}, {period}: {measure.label.toLowerCase()} is measured over{" "}
      <strong>{count(measure.included_count ?? 0)}</strong> of{" "}
      <strong>{count(measure.in_scope_count)}</strong> {measure.entity}.{" "}
      <strong>{count(measure.excluded_count)}</strong> (
      {share(measure.excluded_count, measure.in_scope_count)}) are excluded.
    </p>
  );
}

function ExclusionsTable({
  measures,
  rules,
}: {
  measures: MeasureExclusions[];
  rules: RuleSummary[];
}) {
  const names = new Map(rules.map((rule) => [rule.rule_ref, rule.rule_name]));

  return (
    <div className="table-wrap">
      <table className="plain-table">
        <thead>
          <tr>
            <th scope="col">Measure</th>
            <th scope="col">In scope</th>
            <th scope="col">Counted</th>
            <th scope="col">Excluded</th>
            <th scope="col">Share</th>
            {EXCLUSION_RULES.map((ref) => (
              <th key={ref} scope="col" title={names.get(ref)}>
                {ref}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {measures.map((measure) => {
            if (!measure.applies || measure.in_scope_count === null)
              return (
                <tr key={measure.measure}>
                  <td>
                    {measure.label}
                    <span className="quality__entity">{measure.entity}</span>
                  </td>
                  <td colSpan={4 + EXCLUSION_RULES.length} className="text is-none">
                    No exclusion rules apply
                  </td>
                </tr>
              );

            const byRule = new Map(measure.by_rule.map((rule) => [rule.rule_ref, rule.count]));
            const excluded = measure.excluded_count ?? 0;
            return (
              <tr key={measure.measure}>
                <td>
                  {measure.label}
                  <span className="quality__entity">{measure.entity}</span>
                </td>
                <td>{count(measure.in_scope_count)}</td>
                <td>{count(measure.included_count ?? 0)}</td>
                <td>{count(excluded)}</td>
                <td>{share(excluded, measure.in_scope_count)}</td>
                {EXCLUSION_RULES.map((ref) => {
                  const value = byRule.get(ref);
                  return value === undefined ? (
                    <td key={ref} className="is-none" title="Does not apply to this measure">
                      —
                    </td>
                  ) : (
                    <td key={ref} className={value === 0 ? "is-none" : undefined}>
                      {count(value)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RulesTable({
  rules,
  selected,
  onSelect,
}: {
  rules: RuleSummary[];
  selected: string | null;
  onSelect: (rule: RuleSummary) => void;
}) {
  return (
    <div className="table-wrap">
      <table className="plain-table">
        <thead>
          <tr>
            <th scope="col">Rule</th>
            <th scope="col" className="text">
              Type
            </th>
            <th scope="col" className="text">
              Applied
            </th>
            <th scope="col">Ledger entries</th>
            <th scope="col">
              <span className="visually-hidden">Entries</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rules.map((rule) => (
            <tr
              key={rule.rule_ref}
              className={rule.rule_ref === selected ? "is-selected" : undefined}
            >
              <td>
                <span className="rule-ref">{rule.rule_ref}</span>
                {rule.rule_name}
              </td>
              <td className="text">{rule.kind === "exclusion" ? "Exclusion" : "Repair"}</td>
              <td className="text">{rule.applied === "query" ? "Per period" : "At build"}</td>
              <td className={rule.ledger_count ? undefined : "is-none"}>
                <LedgerCount rule={rule} />
              </td>
              <td>
                {rule.ledger_count ? (
                  <button
                    type="button"
                    className="linkbutton"
                    aria-pressed={rule.rule_ref === selected}
                    onClick={() => onSelect(rule)}
                  >
                    View
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A rule that writes no entries says so, rather than showing a zero that
 * would claim it ran and found nothing. */
function LedgerCount({ rule }: { rule: RuleSummary }) {
  if (rule.ledger_count !== null) return <>{count(rule.ledger_count)}</>;
  if (rule.applied === "query") return <span title="Counted per period, above">Counted above</span>;
  return <span title="This rule writes no ledger entries">Not recorded</span>;
}

function LedgerPanel({ rule, onClose }: { rule: RuleSummary; onClose: () => void }) {
  const [offset, setOffset] = useState(0);

  const { data, isPending, error, isPlaceholderData } = useQuery({
    queryKey: ["ledger", rule.rule_ref, offset],
    queryFn: () => fetchLedger({ rule: rule.rule_ref, limit: LEDGER_PAGE, offset }),
    placeholderData: keepPreviousData,
  });

  return (
    <div className="ledger">
      <div className="table-head">
        <h3>
          <span className="rule-ref">{rule.rule_ref}</span>
          {rule.rule_name}
        </h3>
        <button type="button" className="linkbutton" onClick={onClose}>
          Close
        </button>
      </div>

      {isPending && <p className="empty">Loading entries…</p>}
      {error && <p className="ask__error">{(error as Error).message}</p>}

      {data && (
        <>
          <div className="table-wrap">
            <table className="plain-table">
              <thead>
                <tr>
                  <th scope="col">Record</th>
                  <th scope="col" className="text">
                    Action
                  </th>
                  <th scope="col" className="text">
                    Reason
                  </th>
                  <th scope="col" className="text">
                    Source system
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.entries.map((entry) => (
                  <tr key={entry.ledger_id}>
                    <td>
                      {entry.entity_type.replace(/_/g, " ")}{" "}
                      <span className="mono">{entry.entity_id ?? "—"}</span>
                    </td>
                    <td className="text">{entry.action.toLowerCase()}</td>
                    <td className="text mono">{entry.reason}</td>
                    <td className="text">{entry.source_system ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pager">
            <span>
              {data.total === 0
                ? "No entries"
                : `${count(offset + 1)}–${count(offset + data.entries.length)} of ${count(data.total)}`}
            </span>
            <div className="toggle">
              <button
                type="button"
                disabled={offset === 0 || isPlaceholderData}
                onClick={() => setOffset(Math.max(0, offset - LEDGER_PAGE))}
              >
                Previous
              </button>
              <button
                type="button"
                disabled={offset + LEDGER_PAGE >= data.total || isPlaceholderData}
                onClick={() => setOffset(offset + LEDGER_PAGE)}
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
