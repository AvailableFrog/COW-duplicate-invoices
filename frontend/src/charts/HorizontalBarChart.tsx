import { useMemo } from "react";

import { horizontalBar, type BarDatum } from "./templates";
import { VegaChart } from "./VegaChart";

const numberFormat = new Intl.NumberFormat("en-GB");

interface HorizontalBarChartProps {
  /** The chart's accessible description: what is counted, the total and the date basis. */
  description: string;
  categoryTitle: string;
  valueTitle: string;
  data: readonly BarDatum[];
  /** The caption of the table alternative. */
  tableCaption: string;
  /** Opens a bar's rows; offered by clicking a bar and, for the keyboard, by each table row's button. */
  onSelect?: (key: string) => void;
  /** The accessible name of a table row's button, such as "Show the 40 Pending tickets aged 1 day". */
  selectLabel?: (datum: BarDatum) => string;
  selectedKey?: string | null;
  /** Shown beside the selected bar's value and in its table row, so selection never rests on colour. */
  selectedNote?: string;
}

/**
 * A horizontal bar chart from the trusted template with its table alternative under View data. The table
 * holds every bar's value; when bars can be opened, each row's category is a button doing the same.
 */
export function HorizontalBarChart({
  description,
  categoryTitle,
  valueTitle,
  data,
  tableCaption,
  onSelect,
  selectLabel,
  selectedKey = null,
  selectedNote,
}: HorizontalBarChartProps) {
  const spec = useMemo(
    () =>
      horizontalBar({ description, categoryTitle, valueTitle, data, selectedKey, selectedNote, selectable: Boolean(onSelect) }),
    [description, categoryTitle, valueTitle, data, selectedKey, selectedNote, onSelect],
  );
  return (
    <figure className="bar-chart">
      <VegaChart spec={spec} onSelect={onSelect} />
      <details className="chart-data">
        <summary>View data</summary>
        <table>
          <caption>{tableCaption}</caption>
          <thead>
            <tr>
              <th scope="col">{categoryTitle}</th>
              <th scope="col" className="numeric">
                {valueTitle}
              </th>
            </tr>
          </thead>
          <tbody>
            {data.map((datum) => {
              const selected = datum.key === selectedKey;
              return (
                <tr key={datum.key} className={selected ? "selected" : undefined}>
                  <th scope="row">
                    {onSelect ? (
                      <button
                        type="button"
                        className="link-button"
                        aria-label={selectLabel ? selectLabel(datum) : undefined}
                        aria-current={selected ? "true" : undefined}
                        onClick={() => onSelect(datum.key)}
                      >
                        {datum.label}
                      </button>
                    ) : (
                      datum.label
                    )}
                    {selected && selectedNote ? <span className="muted"> · {selectedNote}</span> : null}
                  </th>
                  <td className="numeric num">{numberFormat.format(datum.value)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
