"use client";

import { useEffect, useRef } from "react";

import type { PricePoint } from "@/lib/types";

type ChartMarker = {
  day: string;
  type: "utterance" | "target" | "resolution";
  /** For resolution: outcome 1=hit, 0=miss, 0.5=partial */
  outcome?: number;
  targetPrice?: number;
};

type PriceChartProps = {
  /** Daily closes from t0 to resolution; null or empty = honest placeholder. */
  series: PricePoint[] | null;
  markers?: ChartMarker[];
};

/**
 * Price chart from utterance to resolution (FR-403, US-004), built on
 * TradingView Lightweight Charts v4. One ink line; three canonical markers:
 *   - utterance: Brier Blue (#2D54CE) dot
 *   - target: dashed ochre (#BC8A2C) horizontal price line
 *   - resolution: band-colored dot (hit #0E7C66 / miss #B23A2E / partial #BC8A2C)
 *
 * No gradients, no area-fill, no dual axes (BRANDKIT §5).
 * Respects prefers-reduced-motion.
 * Guards SSR by checking typeof window.
 */
export function PriceChart({ series, markers = [] }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!series || series.length === 0) return;
    const container = containerRef.current;
    if (!container) return;

    let destroyed = false;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let chartInstance: any = null;
    let roInstance: ResizeObserver | null = null;
    let tooltipEl: HTMLDivElement | null = null;

    void (async () => {
      const lc = await import("lightweight-charts");
      if (destroyed || !container) return;

      const prefersReduced =
        typeof window !== "undefined" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;

      chartInstance = lc.createChart(container, {
        width: container.clientWidth,
        height: 220,
        layout: {
          background: { color: "#FCFBF8" },
          textColor: "#565C64",
          fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
          fontSize: 11,
        },
        grid: {
          vertLines: { color: "#15191D1A" },
          horzLines: { color: "#15191D1A" },
        },
        crosshair: {
          mode: lc.CrosshairMode.Normal,
        },
        rightPriceScale: {
          borderColor: "#15191D1A",
        },
        timeScale: {
          borderColor: "#15191D1A",
          timeVisible: false,
          fixLeftEdge: true,
          fixRightEdge: true,
        },
        handleScroll: !prefersReduced,
        handleScale: !prefersReduced,
      });

      // One ink line (BRANDKIT §5)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const lineSeries: any = chartInstance.addLineSeries({
        color: "#16191D",
        lineWidth: 1.5,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: true,
        crosshairMarkerRadius: 3,
      });

      lineSeries.setData(
        (series ?? []).map((p: PricePoint) => ({
          time: p.day,
          value: p.closeUsd,
        })),
      );

      // Markers: utterance (blue dot), resolution (colored dot)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const chartMarkers: any[] = [];

      for (const m of markers) {
        if (m.type === "utterance") {
          chartMarkers.push({
            time: m.day,
            position: "inBar",
            shape: "circle",
            color: "#2D54CE",
            size: 1,
          });
        } else if (m.type === "resolution") {
          const color =
            m.outcome === 1 ? "#0E7C66" : m.outcome === 0 ? "#B23A2E" : "#BC8A2C";
          chartMarkers.push({
            time: m.day,
            position: "inBar",
            shape: "circle",
            color,
            size: 1,
          });
        }
      }

      if (chartMarkers.length > 0) {
        lineSeries.setMarkers(
          [...chartMarkers].sort((a: { time: string }, b: { time: string }) =>
            a.time < b.time ? -1 : 1,
          ),
        );
      }

      // Target price horizontal line (ochre dashed) — BRANDKIT §5
      for (const m of markers) {
        if (m.type === "target" && m.targetPrice != null) {
          lineSeries.createPriceLine({
            price: m.targetPrice,
            color: "#BC8A2C",
            lineWidth: 1,
            lineStyle: 2, // LineStyle.Dashed = 2
            axisLabelVisible: true,
            title: "target",
          });
        }
      }

      // Tabular tooltip with the sourced daily-close value (BRANDKIT §5).
      tooltipEl = document.createElement("div");
      tooltipEl.style.cssText = [
        "position:absolute",
        "display:none",
        "pointer-events:none",
        "z-index:5",
        "padding:6px 8px",
        "border:1px solid #15191D33",
        "background:#FCFBF8",
        "border-radius:3px",
        "font-family:'IBM Plex Mono', ui-monospace, monospace",
        "font-size:10px",
        "font-variant-numeric:tabular-nums",
        "line-height:1.4",
        "color:#2C3036",
        "white-space:nowrap",
        "box-shadow:0 1px 2px #15191D14",
      ].join(";");
      container.style.position = "relative";
      container.appendChild(tooltipEl);

      const fmtTime = (t: unknown): string => {
        if (typeof t === "string") return t;
        if (t && typeof t === "object" && "year" in t) {
          const d = t as { year: number; month: number; day: number };
          return `${d.year}-${String(d.month).padStart(2, "0")}-${String(d.day).padStart(2, "0")}`;
        }
        return String(t);
      };

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      chartInstance.subscribeCrosshairMove((param: any) => {
        if (
          !tooltipEl ||
          !param ||
          !param.time ||
          !param.point ||
          param.point.x < 0 ||
          param.point.y < 0
        ) {
          if (tooltipEl) tooltipEl.style.display = "none";
          return;
        }
        const point = param.seriesData.get(lineSeries);
        const value =
          point && typeof point === "object" && "value" in point
            ? (point as { value: number }).value
            : null;
        if (value == null) {
          tooltipEl.style.display = "none";
          return;
        }
        const priceText =
          "$" +
          Number(value).toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          });
        tooltipEl.innerHTML =
          `<div>${fmtTime(param.time)}</div>` +
          `<div style="color:#16191D;font-weight:500">${priceText}</div>` +
          `<div style="color:#8A8F96">UTC daily close</div>`;
        tooltipEl.style.display = "block";
        const x = Math.min(Math.max(0, param.point.x + 12), container.clientWidth - 124);
        const y = Math.max(0, param.point.y - 12);
        tooltipEl.style.left = `${x}px`;
        tooltipEl.style.top = `${y}px`;
      });

      chartInstance.timeScale().fitContent();

      // Responsive resize
      roInstance = new ResizeObserver(() => {
        if (chartInstance && container) {
          chartInstance.applyOptions({ width: container.clientWidth });
        }
      });
      roInstance.observe(container);
    })();

    return () => {
      destroyed = true;
      roInstance?.disconnect();
      tooltipEl?.remove();
      tooltipEl = null;
      chartInstance?.remove();
      chartInstance = null;
    };
  }, [series, markers]);

  if (!series || series.length === 0) {
    return (
      <div className="flex min-h-[120px] items-center justify-center rounded-[3px] border border-line-2 bg-surface-2">
        <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-4">
          Price data not yet available for this claim window.
        </span>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="w-full overflow-hidden rounded-[3px] border border-line-2"
      style={{ minHeight: 220 }}
      aria-label="Price chart from utterance to resolution"
    />
  );
}
