import { Topbar } from "./components/Topbar";
import { LandingView } from "./features/landing/LandingView";
import { QualityView } from "./features/quality/QualityView";
import { useScope } from "./lib/scope";

export default function App() {
  const scope = useScope();

  return (
    <>
      <Topbar
        view={scope.view}
        viewHref={scope.viewHref}
        onViewChange={scope.setView}
        regionId={scope.regionId}
        period={scope.period}
        onRegionChange={scope.setRegionId}
        onPeriodChange={scope.setPeriod}
      />
      {scope.view === "quality" ? (
        <QualityView regionId={scope.regionId} period={scope.period} />
      ) : (
        <LandingView
          unit={scope.unit}
          regionId={scope.regionId}
          period={scope.period}
          onUnitChange={scope.setUnit}
        />
      )}
    </>
  );
}
