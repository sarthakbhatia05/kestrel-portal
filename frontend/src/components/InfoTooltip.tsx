import { useId } from "react";

/**
 * A plain-language definition next to a metric's title. Hover or focus
 * reveals it; the trigger stays keyboard-reachable via aria-describedby.
 */
export function InfoTooltip({ text }: { text: string }) {
  const id = useId();

  return (
    <span className="info-tip">
      <button type="button" className="info-tip__trigger" aria-describedby={id}>
        i
      </button>
      <span role="tooltip" id={id} className="info-tip__bubble">
        {text}
      </span>
    </span>
  );
}
