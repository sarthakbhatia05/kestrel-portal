import { useRef, useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { fetchAskCapability, fetchScope, streamAsk } from "../../api/client";
import type { AskAnswer, AskResult, AskTurn, StepRecord } from "../../api/types";

const EXAMPLES = [
  "Which five outlets had the worst fill rate last quarter?",
  "Why did fill rate drop in the West last week?",
  "Where is near-expiry stock concentrated?",
];

/** The last ten turns, overlapping, questions and what they resolved to. */
const WINDOW_SIZE = 10;

const percent = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(1)}%`;

interface Turn {
  question: string;
  steps: StepRecord[];
  answer: AskAnswer | null;
  error: string | null;
}

/**
 * A row's headline figure differs by metric, so the breakdown reads the
 * field that metric actually computed rather than guessing a shape.
 */
function rowValue(result: AskResult, row: Record<string, unknown>): string {
  const metric = result.basis.metric;
  if (metric === "fill_rate") return percent(row.value as number | null);
  if (metric === "otif") return percent(row.otif as number | null);
  if (metric === "returns") return percent(row.returns_rate as number | null);
  if (metric === "near_expiry") return percent(row.near_expiry_rate as number | null);
  return percent(row.excursion_rate as number | null);
}

function Supporting({ result }: { result: AskResult }) {
  const rows = result.rows.slice(0, 5);
  if (rows.length === 0) return null;
  return (
    <table className="ask__rows">
      <thead>
        <tr>
          <th scope="col">Breakdown</th>
          <th scope="col">Rate</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.key}>
            <td>{row.label}</td>
            <td>{rowValue(result, row as unknown as Record<string, unknown>)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * What the investigation actually measured, in order.
 *
 * This is the honesty surface. The explanation above it is the model
 * reasoning about figures; this is the list of real queries that produced
 * them, each with the sentence stating its figure, period, scope and
 * exclusions. A reader who distrusts the prose can check it here.
 */
function Trail({ steps, live }: { steps: StepRecord[]; live: boolean }) {
  if (steps.length === 0) return null;
  const body = (
    <ol className="ask__trail">
      {steps.map((step, index) => (
        <li key={index} className={step.error ? "is-failed" : undefined}>
          <p className="ask__step-reason">{step.reasoning}</p>
          {step.error ? (
            <p className="ask__step-error">Could not measure: {step.error}</p>
          ) : (
            <p className="ask__step-summary">{step.summary}</p>
          )}
          {step.delta !== null && (
            <p className="ask__step-delta">
              {step.delta >= 0 ? "Up" : "Down"}{" "}
              <span className="mono">{Math.abs(step.delta * 100).toFixed(2)}</span>{" "}
              percentage points{step.delta_basis ? ` from ${step.delta_basis}` : ""}.
            </p>
          )}
        </li>
      ))}
    </ol>
  );

  // While it runs, the steps are the content. Once the answer lands they
  // become supporting evidence, folded away but one click from view.
  if (live) return body;
  return (
    <details className="ask__trail-wrap">
      <summary>
        {steps.length} measurement{steps.length === 1 ? "" : "s"} taken
      </summary>
      {body}
    </details>
  );
}

/**
 * Ask anything (PRD C4).
 *
 * The panel renders the deterministic answer as the answer of record;
 * `prose` is model framing that already passed the server's numeric guard
 * and is shown above it, never instead of it. When the language capability
 * is not configured the panel says so and every dashboard figure is
 * unaffected (C4.6).
 */
export function AskPanel({
  regionId,
  period,
}: {
  regionId: number | null;
  period: string;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const log = useRef<HTMLDivElement>(null);

  const capability = useQuery({
    queryKey: ["ask-capability"],
    queryFn: fetchAskCapability,
  });
  // Shares react-query's cache with ScopeBar, so naming the scope here
  // costs no extra request.
  const scope = useQuery({ queryKey: ["scope"], queryFn: fetchScope });

  const regionName =
    regionId === null
      ? "All regions"
      : (scope.data?.regions.find((r) => r.region_id === regionId)?.region_name ??
        `Region ${regionId}`);
  const periodLabel =
    scope.data?.periods.find((p) => p.value === period)?.label ?? period;

  const scrollDown = () =>
    requestAnimationFrame(() => log.current?.scrollTo(0, log.current.scrollHeight));

  const submit = async (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || pending) return;
    setDraft("");
    setPending(true);

    const index = turns.length;
    const window: AskTurn[] = turns
      .filter((turn) => turn.answer?.intent)
      .slice(-WINDOW_SIZE)
      .map((turn) => ({ question: turn.question, intent: turn.answer!.intent! }));

    setTurns((previous) => [
      ...previous,
      { question: trimmed, steps: [], answer: null, error: null },
    ]);
    scrollDown();

    const patch = (change: (turn: Turn) => Turn) =>
      setTurns((previous) =>
        previous.map((turn, position) => (position === index ? change(turn) : turn)),
      );

    try {
      await streamAsk({ question: trimmed, window, regionId, period }, (event) => {
        if (event.type === "step") {
          const { type: _type, ...step } = event;
          patch((turn) => ({ ...turn, steps: [...turn.steps, step] }));
        } else if (event.type === "answer") {
          const { type: _type, ...answer } = event;
          patch((turn) => ({ ...turn, answer, steps: answer.steps ?? turn.steps }));
        } else {
          patch((turn) => ({ ...turn, error: event.message }));
        }
        scrollDown();
      });
    } catch (error) {
      patch((turn) => ({ ...turn, error: (error as Error).message }));
    } finally {
      setPending(false);
      scrollDown();
    }
  };

  if (capability.isPending) return null;

  // PRD C4.6: the product stays fully usable without the language
  // capability. The panel says so rather than disappearing -- a surface
  // that silently vanishes reads as a broken build, not a deliberate
  // degradation.
  if (!capability.data?.available)
    return (
      <section className="card ask ask--unavailable" aria-label="Ask anything">
        <header className="card__head">
          <div className="card__title">
            <h2>Ask</h2>
          </div>
        </header>
        <p className="ask__unavailable">
          Ask-anything is unavailable: no language model is configured. Every
          figure below is unaffected.
        </p>
        <ul className="ask__supported">
          {(capability.data?.supported_metrics ?? []).map((metric) => (
            <li key={metric}>{metric}</li>
          ))}
        </ul>
      </section>
    );

  return (
    <section className="card ask" aria-label="Ask anything">
      <header className="card__head">
        <div className="card__title">
          <h2>Ask</h2>
        </div>
        <span className="ask__scope">
          {regionName} &middot; {periodLabel}
        </span>
      </header>

      <div className="ask__log" ref={log} aria-live="polite">
        {turns.length === 0 && (
          <div className="ask__empty">
            <p>
              Ask about fill rate, OTIF, returns, near-expiry stock or excursions —
              or ask why one of them moved.
            </p>
            <ul className="ask__examples">
              {EXAMPLES.map((example) => (
                <li key={example}>
                  <button type="button" onClick={() => void submit(example)}>
                    {example}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {turns.map((turn, index) => (
          <div key={index} className="ask__turn">
            <p className="ask__question">{turn.question}</p>

            <Trail steps={turn.steps} live={turn.answer === null && turn.error === null} />

            {turn.answer === null && turn.error === null && (
              <p className="ask__pending">
                {turn.steps.length === 0 ? "Reading the question…" : "Measuring…"}
              </p>
            )}

            {turn.answer && (
              <div
                className={turn.answer.declined ? "ask__answer is-declined" : "ask__answer"}
              >
                {turn.answer.prose && <p className="ask__prose">{turn.answer.prose}</p>}
                <p className="ask__record">{turn.answer.answer}</p>
                {turn.answer.result && <Supporting result={turn.answer.result} />}
              </div>
            )}

            {turn.error && <p className="ask__error">{turn.error}</p>}
          </div>
        ))}
      </div>

      <form
        className="ask__form"
        onSubmit={(event) => {
          event.preventDefault();
          void submit(draft);
        }}
      >
        <input
          type="text"
          value={draft}
          maxLength={500}
          placeholder="Ask a question about the measured data"
          aria-label="Question"
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit" disabled={pending || draft.trim() === ""}>
          Ask
        </button>
      </form>
    </section>
  );
}
