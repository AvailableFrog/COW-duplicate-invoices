// Trusted chart templates (PRD section 7, ADR 0002). A chart is never an arbitrary Vega-Lite specification:
// it is built here from typed rows, with its data inline, a zero baseline, direct labels and an accessible
// description. Templates write no expressions and no data URLs, and VegaChart refuses any specification that
// carries one, so neither a source value nor a future query plan can make a chart load or run anything.

import type { TopLevelSpec } from "vega-lite";

/** The PRD section 6 palette, matching the tokens in styles.css. */
export const CHART_COLOURS = {
  ink: "#1f2328",
  muted: "#5f6b73",
  line: "#dcd9d2",
  accent: "#0f7b7b",
  // The selected bar: darker than the accent, and always named in its label too, never colour alone.
  selected: "#0a4747",
  unresolved: "#b4690e",
} as const;

const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
const BAR_STEP = 30;
const BAR_THICKNESS = 18;

/** One bar: a stable key the chart reports when clicked, the category label and a non-negative value. */
export interface BarDatum {
  key: string;
  label: string;
  value: number;
}

export interface HorizontalBarInput {
  /** Read out as the chart's accessible name; say what is counted, the total and the date basis. */
  description: string;
  categoryTitle: string;
  valueTitle: string;
  /** In display order; the bars keep it. */
  data: readonly BarDatum[];
  /** The bar whose rows are listed elsewhere: drawn darker and labelled with `selectedNote`. */
  selectedKey?: string | null;
  selectedNote?: string;
  /** Show a pointer over the bars; VegaChart reports clicks by key. */
  selectable?: boolean;
}

const numberFormat = new Intl.NumberFormat("en-GB");

/**
 * Horizontal bars with the value printed at each bar's tip. The value axis starts at zero and is left
 * implicit, since every bar is labelled; categories keep the order given.
 */
export function horizontalBar(input: HorizontalBarInput): TopLevelSpec {
  const values = input.data.map((datum) => {
    if (!Number.isFinite(datum.value) || datum.value < 0) throw new Error(`bar ${datum.key} needs a non-negative value`);
    const selected = datum.key === input.selectedKey;
    return {
      key: datum.key,
      label: datum.label,
      value: datum.value,
      tone: selected ? "selected" : "base",
      tip: `${numberFormat.format(datum.value)}${selected && input.selectedNote ? ` · ${input.selectedNote}` : ""}`,
    };
  });
  const largest = Math.max(1, ...values.map((value) => value.value));
  const y = {
    field: "label",
    type: "nominal" as const,
    sort: null,
    title: null,
    axis: { ticks: false, domain: false, labelColor: CHART_COLOURS.ink, labelFontSize: 13, labelPadding: 8, labelLimit: 160 },
  };
  const x = {
    field: "value",
    type: "quantitative" as const,
    // Room past the longest bar for its label; the baseline is always zero.
    scale: { zero: true, nice: false, domainMin: 0, domainMax: largest * 1.3 },
    axis: null,
    title: input.valueTitle,
  };
  return {
    description: input.description,
    width: "container",
    height: { step: BAR_STEP },
    background: "transparent",
    data: { values },
    layer: [
      {
        mark: {
          type: "rule",
          color: CHART_COLOURS.muted,
          strokeWidth: 1,
          aria: false,
        },
        encoding: { x: { datum: 0, type: "quantitative", scale: x.scale, axis: null } },
      },
      {
        mark: {
          type: "bar",
          size: BAR_THICKNESS,
          cornerRadiusEnd: 4,
          cursor: input.selectable ? "pointer" : "default",
        },
        encoding: {
          y,
          x,
          color: {
            field: "tone",
            type: "nominal",
            scale: { domain: ["base", "selected"], range: [CHART_COLOURS.accent, CHART_COLOURS.selected] },
            legend: null,
          },
          tooltip: [
            { field: "label", type: "nominal", title: input.categoryTitle },
            { field: "value", type: "quantitative", title: input.valueTitle, format: "," },
          ],
        },
      },
      {
        mark: {
          type: "text",
          align: "left",
          baseline: "middle",
          dx: 6,
          fontSize: 13,
          color: CHART_COLOURS.ink,
          cursor: input.selectable ? "pointer" : "default",
          aria: false,
        },
        encoding: { y, x, text: { field: "tip", type: "nominal" } },
      },
    ],
    config: {
      font: FONT,
      view: { stroke: null },
      axis: { labelFont: FONT, titleFont: FONT },
    },
  };
}

// Data URLs, expressions and transforms: the service computes every number, so a chart only draws rows.
const FORBIDDEN_KEYS = new Set(["url", "expr", "calculate", "signal", "test", "filter", "params", "transform"]);

/** Refuse a specification that names a data URL or carries an expression: charts take inline data only. */
export function assertTrusted(spec: unknown, path = "spec"): void {
  if (Array.isArray(spec)) {
    spec.forEach((item, index) => assertTrusted(item, `${path}[${index}]`));
    return;
  }
  if (spec === null || typeof spec !== "object") return;
  for (const [key, value] of Object.entries(spec)) {
    // Row values are data, never read as specification.
    if (key === "values" && path.endsWith(".data")) continue;
    if (FORBIDDEN_KEYS.has(key)) {
      throw new Error(`untrusted chart specification: ${path}.${key} is not allowed`);
    }
    assertTrusted(value, `${path}.${key}`);
  }
}

/** The service's chart templates (chart_templates.py): an Explore result names one of these in `usermeta`. */
export const SERVICE_TEMPLATES = ["bar_horizontal", "bar_vertical"] as const;
export type ServiceTemplateId = (typeof SERVICE_TEMPLATES)[number];

/**
 * Accept a specification the service filled from one of its templates: it names a known template, its data is
 * an inline array and nothing else, and it carries no URL, expression, filter, parameter or transform. Anything
 * else is refused before Vega sees it, so a result can only ever be drawn as the template it claims to be.
 */
export function assertServiceTemplate(spec: unknown, expected: string): TopLevelSpec {
  if (spec === null || typeof spec !== "object" || Array.isArray(spec)) throw new Error("untrusted chart specification: not an object");
  const record = spec as Record<string, unknown>;
  const template = (record.usermeta as { template?: unknown } | undefined)?.template;
  if (typeof template !== "string" || !(SERVICE_TEMPLATES as readonly string[]).includes(template) || template !== expected) {
    throw new Error(`untrusted chart specification: ${String(template)} is not a trusted template`);
  }
  const data = record.data as Record<string, unknown> | undefined;
  if (!data || Object.keys(data).join() !== "values" || !Array.isArray(data.values)) {
    throw new Error("untrusted chart specification: data must be inline values only");
  }
  assertTrusted(spec);
  return spec as TopLevelSpec;
}
