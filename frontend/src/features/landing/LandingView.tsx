import { useScope } from "../../lib/scope";
import { FillRateCard } from "../service/FillRateCard";
import { NearExpiryCard } from "../service/NearExpiryCard";
import { OtifCard } from "../service/OtifCard";
import { ReturnsCard } from "../service/ReturnsCard";

/**
 * The landing view is an exception surface, not a canvas (G2, C2.3).
 * Worst performers are visible on entry, with no drill-down required.
 */
export function LandingView() {
  const { unit, regionId, period, setUnit } = useScope();

  return (
    <>
      <div className="topbar">
        <span className="topbar__mark">Kestrel</span>
        <span className="topbar__scope">
          {regionId === null ? "All regions" : `Region ${regionId}`} &middot;{" "}
          {period === "latest" ? "Latest period" : period}
        </span>
      </div>
      <main className="page">
        <header className="page__head">
          <h1>Control tower</h1>
          <p>Where we are losing service, and where we are losing money.</p>
        </header>

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
          </section>
        </div>
      </main>
    </>
  );
}
