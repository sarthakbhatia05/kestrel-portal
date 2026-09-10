import { useScope } from "../../lib/scope";
import { ScopeBar } from "./ScopeBar";
import { AskPanel } from "../ask/AskPanel";
import { ExcursionsCard } from "../service/ExcursionsCard";
import { FillRateCard } from "../service/FillRateCard";
import { NearExpiryCard } from "../service/NearExpiryCard";
import { OtifCard } from "../service/OtifCard";
import { ReturnsCard } from "../service/ReturnsCard";

/**
 * The landing view is an exception surface, not a canvas (G2, C2.3).
 * Worst performers are visible on entry, with no drill-down required.
 */
export function LandingView() {
  const { unit, regionId, period, setUnit, setRegionId, setPeriod } = useScope();

  return (
    <>
      <div className="topbar">
        <span className="topbar__mark">Kestrel</span>
        <ScopeBar
          regionId={regionId}
          period={period}
          onRegionChange={setRegionId}
          onPeriodChange={setPeriod}
        />
      </div>
      <main className="page">
        <header className="page__head">
          <h1>Control tower</h1>
          <p>Where we are losing service, and where we are losing money.</p>
        </header>

        <AskPanel regionId={regionId} period={period} />

        <div className="grid">
          <section className="group group--service" aria-label="Service loss">
            <FillRateCard
              unit={unit}
              regionId={regionId}
              period={period}
              onUnitChange={setUnit}
            />
            <OtifCard regionId={regionId} period={period} />
          </section>

          <section className="group group--money" aria-label="Money loss">
            <ReturnsCard regionId={regionId} period={period} />
            <NearExpiryCard regionId={regionId} />
            <ExcursionsCard regionId={regionId} period={period} />
          </section>
        </div>
      </main>
    </>
  );
}
