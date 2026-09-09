import { useScope } from "../../lib/scope";
import { FillRateCard } from "../service/FillRateCard";
import { OtifCard } from "../service/OtifCard";

/**
 * The landing view is an exception surface, not a canvas (G2, C2.3).
 * Worst performers are visible on entry, with no drill-down required.
 */
export function LandingView() {
  const { unit, regionId, period, setUnit } = useScope();

  return (
    <main className="page">
      <header className="page__head">
        <h1>Kestrel Control Tower</h1>
        <p>Where we are losing service and where we are losing money.</p>
      </header>
      <FillRateCard
        unit={unit}
        regionId={regionId}
        period={period}
        onUnitChange={setUnit}
      />
      <OtifCard regionId={regionId} period={period} />
    </main>
  );
}
