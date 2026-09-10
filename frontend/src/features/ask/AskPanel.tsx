import { useRef, useState } from "react";

import { useMutation, useQuery } from "@tanstack/react-query";

import { fetchAskCapability, postAsk } from "../../api/client";
import type { AskAnswer, AskResult, AskTurn } from "../../api/types";

const EXAMPLES = [
  "Which five outlets had the worst fill rate last quarter?",
  "How is OTIF in the West region?",
  "Where is near-expiry stock concentrated?",
];

/** The last ten turns, overlapping, questions and what they resolved to. */
const WINDOW_SIZE = 10;

const percent = (value: number | null) =>
  value === null ? "—" : `${(value * 100).toFixed(1)}%`;

interface Turn {
  question: string;
  answer: AskAnswer;
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
 * Ask anything (PRD C4).
 *
 * The panel renders the deterministic answer as the answer of record;
 * `prose` is model framing that already passed the server's numeric guard
 * and is shown above it, never instead of it. When the language capability
 * is not configured the panel does not render at all, and every dashboard
 * figure is unaffected (C4.6).
 */
export function AskPanel({ regionId }: { regionId: number | null }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const log = useRef<HTMLDivElement>(null);

  const capability = useQuery({
    queryKey: ["ask-capability"],
    queryFn: fetchAskCapability,
  });

  const ask = useMutation({
    mutationFn: (question: string) =>
      postAsk({
        question,
        window: turns
          .filter((turn): turn is Turn & { answer: AskAnswer } => turn.answer.intent !== null)
          .slice(-WINDOW_SIZE)
          .map<AskTurn>((turn) => ({
            question: turn.question,
            intent: turn.answer.intent!,
          })),
        regionId,
      }),
    onSuccess: (answer) => {
      setTurns((previous) => [...previous, { question: answer.question, answer }]);
      requestAnimationFrame(() => log.current?.scrollTo(0, log.current.scrollHeight));
    },
  });

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

  const submit = (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || ask.isPending) return;
    setDraft("");
    ask.mutate(trimmed);
  };

  return (
    <section className="card ask" aria-label="Ask anything">
      <header className="card__head">
        <div className="card__title">
          <h2>Ask</h2>
        </div>
        <span className="ask__scope">
          {regionId === null ? "All regions" : `Region ${regionId}`}
        </span>
      </header>

      <div className="ask__log" ref={log} aria-live="polite">
        {turns.length === 0 && (
          <div className="ask__empty">
            <p>Ask about fill rate, OTIF, returns, near-expiry stock or excursions.</p>
            <ul className="ask__examples">
              {EXAMPLES.map((example) => (
                <li key={example}>
                  <button type="button" onClick={() => submit(example)}>
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
            <div
              className={turn.answer.declined ? "ask__answer is-declined" : "ask__answer"}
            >
              {turn.answer.prose && <p className="ask__prose">{turn.answer.prose}</p>}
              <p className="ask__record">{turn.answer.answer}</p>
              {turn.answer.result && <Supporting result={turn.answer.result} />}
            </div>
          </div>
        ))}

        {ask.isPending && <p className="ask__pending">Working…</p>}
        {ask.error && (
          <p className="ask__error">{(ask.error as Error).message}</p>
        )}
      </div>

      <form
        className="ask__form"
        onSubmit={(event) => {
          event.preventDefault();
          submit(draft);
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
        <button type="submit" disabled={ask.isPending || draft.trim() === ""}>
          Ask
        </button>
      </form>
    </section>
  );
}
