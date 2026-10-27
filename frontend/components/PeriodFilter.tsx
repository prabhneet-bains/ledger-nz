"use client";

import { useEffect, useState } from "react";
import { PERIOD_EVENT, PERIOD_PRESETS, Period, defaultPeriod, formatPeriod, loadPeriod, rangeFor, savePeriod } from "@/lib/period";

export function usePeriod(): Period {
  const [period, setPeriod] = useState<Period>(() => defaultPeriod());

  useEffect(() => {
    const sync = () => setPeriod(loadPeriod());
    sync();
    window.addEventListener(PERIOD_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(PERIOD_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return period;
}

export default function PeriodFilter() {
  const period = usePeriod();
  const invalid = Boolean(period.start && period.end && period.start > period.end);

  function choose(preset: Period["preset"]) {
    if (preset === "custom") {
      savePeriod(rangeFor("custom", new Date(), { start: period.start, end: period.end }));
      return;
    }
    savePeriod(rangeFor(preset));
  }

  return (
    <div className="period-bar">
      <div className="period-presets" role="group" aria-label="Date range">
        {PERIOD_PRESETS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={period.preset === item.id ? "preset active" : "preset"}
            onClick={() => choose(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {period.preset === "custom" ? (
        <div className="row">
          <label>
            From
            <input
              type="date"
              value={period.start}
              onChange={(event) => savePeriod({ ...period, preset: "custom", start: event.target.value })}
            />
          </label>
          <label>
            To
            <input
              type="date"
              value={period.end}
              onChange={(event) => savePeriod({ ...period, preset: "custom", end: event.target.value })}
            />
          </label>
        </div>
      ) : null}
      <p className={invalid ? "error" : "hint"}>{invalid ? "The end date is before the start date." : formatPeriod(period)}</p>
    </div>
  );
}
