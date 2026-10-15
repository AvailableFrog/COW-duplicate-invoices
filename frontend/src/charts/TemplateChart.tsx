import { useMemo, type ReactNode } from "react";

import { assertServiceTemplate } from "./templates";
import { VegaChart } from "./VegaChart";

interface TemplateChartProps {
  /** The template the service says it filled; the specification must name the same one. */
  template: string;
  /** A specification the service built from that template, with inline data. */
  spec: Record<string, unknown>;
  /** The table alternative under View data: every row, including any the chart combines or leaves out. */
  table: ReactNode;
  /** Called with a clicked mark's key; the table's row buttons offer the same by keyboard. */
  onSelect?: (key: string) => void;
}

/**
 * Draw a chart the service filled from one of its trusted templates, refusing it here too unless it is one,
 * with its table alternative under View data. A refused specification is never drawn; the table still is.
 */
export function TemplateChart({ template, spec, table, onSelect }: TemplateChartProps) {
  const checked = useMemo(() => {
    try {
      return { spec: assertServiceTemplate(spec, template), error: "" };
    } catch (error: unknown) {
      return { spec: null, error: error instanceof Error ? error.message : String(error) };
    }
  }, [spec, template]);
  return (
    <figure className="bar-chart">
      {checked.spec ? (
        <VegaChart spec={checked.spec} onSelect={onSelect} />
      ) : (
        <p className="notice notice-error" role="alert">
          The chart was not drawn because its specification is not a trusted template ({checked.error}). Its numbers are
          in the table under View data.
        </p>
      )}
      <details className="chart-data">
        <summary>View data</summary>
        {table}
      </details>
    </figure>
  );
}
