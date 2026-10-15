import { useEffect, useRef, useState } from "react";
import type { TopLevelSpec } from "vega-lite";

import { assertTrusted } from "./templates";

interface VegaChartProps {
  /** A specification from a trusted template in templates.ts, never one assembled elsewhere. */
  spec: TopLevelSpec;
  /** Called with the clicked mark's `key`; the table alternative offers the same action by keyboard. */
  onSelect?: (key: string) => void;
}

function refuse(): Promise<never> {
  return Promise.reject(new Error("charts take inline data only; nothing is loaded from a URL or file"));
}

/**
 * Render a trusted Vega-Lite specification as SVG. Vega is loaded on first use, so the rest of the page does
 * not wait for it. Its loader refuses every URL and file, and expressions run through Vega's interpreter
 * rather than compiled code; the specification is checked for data URLs and expressions before embedding.
 */
export function VegaChart({ spec, onSelect }: VegaChartProps) {
  const container = useRef<HTMLDivElement>(null);
  const select = useRef(onSelect);
  const [failure, setFailure] = useState("");
  select.current = onSelect;

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    let cancelled = false;
    let finalize: (() => void) | null = null;
    (async () => {
      assertTrusted(spec);
      const [{ default: embed }, vega] = await Promise.all([import("vega-embed"), import("vega")]);
      if (cancelled) return;
      const loader = vega.loader();
      loader.load = refuse;
      loader.sanitize = refuse;
      loader.http = refuse;
      loader.file = refuse;
      const result = await embed(element, spec, {
        mode: "vega-lite",
        renderer: "svg",
        actions: false,
        ast: true,
        loader,
        tooltip: { theme: "light" },
        // A container width with a step height makes Vega-Lite log a harmless "Dropping fit-y" on every chart.
        logLevel: vega.Error,
      });
      if (cancelled) {
        result.finalize();
        return;
      }
      finalize = result.finalize;
      result.view.addEventListener("click", (_event, item) => {
        const key = (item?.datum as { key?: unknown } | undefined)?.key;
        if (typeof key === "string") select.current?.(key);
      });
      setFailure("");
    })().catch((error: unknown) => {
      if (!cancelled) setFailure(error instanceof Error ? error.message : String(error));
    });
    return () => {
      cancelled = true;
      finalize?.();
    };
  }, [spec]);

  return (
    <>
      {/* Vega names this container (role graphics-document) with the template's description. */}
      <div ref={container} className="vega-chart" />
      {failure ? (
        <p className="notice notice-error" role="alert">
          The chart could not be drawn ({failure}). Its numbers are in the table under View data.
        </p>
      ) : null}
    </>
  );
}
