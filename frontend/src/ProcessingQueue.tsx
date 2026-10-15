import { useEffect, useMemo, useRef, useState } from "react";

import {
  fetchBucketTickets,
  type BucketTicket,
  type BucketTicketsResponse,
  type FilterState,
  type ProcessingQueueResponse,
  type QueueChart,
} from "./api";
import { HorizontalBarChart } from "./charts/HorizontalBarChart";
import type { BarDatum } from "./charts/templates";

/** Opens one Ticket from a bucket in the drawer; `opener` gets focus back when the drawer closes. */
export type OpenQueueTicket = (ticket: BucketTicket, population: string, fingerprint: string, opener: HTMLButtonElement) => void;

interface Selection {
  metricId: string;
  bucketId: string;
}

type Drilldown =
  | { kind: "loading"; selection: Selection }
  | { kind: "ready"; selection: Selection; data: BucketTicketsResponse }
  | { kind: "failed"; selection: Selection; message: string };

const numberFormat = new Intl.NumberFormat("en-GB");
const SELECTED_NOTE = "listed below";

function plural(count: number, one: string, many: string): string {
  return `${numberFormat.format(count)} ${count === 1 ? one : many}`;
}

function days(count: number): string {
  return plural(count, "day", "days");
}

function timestamp(value: string | null): string {
  return value ? value.replace("T", " ").slice(0, 16) : "not usable";
}

/** The total and its spread, in words: "129 tickets · median 2 days · oldest 33 days". */
function totalLine(chart: QueueChart): string {
  const parts = [plural(chart.total, "ticket", "tickets")];
  if (chart.summary && chart.summary.median !== null) parts.push(`median ${days(chart.summary.median)}`);
  if (chart.summary && chart.summary.max !== null) parts.push(`oldest ${days(chart.summary.max)}`);
  return parts.join(" · ");
}

interface QueueChartCardProps {
  chart: QueueChart;
  asOf: string;
  registry: string;
  selected: Selection | null;
  onSelect: (selection: Selection) => void;
}

function QueueChartCard({ chart, asOf, registry, selected, onSelect }: QueueChartCardProps) {
  const headingId = `queue-${chart.metric_id}`;
  const data: BarDatum[] = useMemo(
    () => chart.buckets.map((bucket) => ({ key: bucket.id, label: bucket.label, value: bucket.tickets })),
    [chart.buckets],
  );
  const selectedKey = selected?.metricId === chart.metric_id ? selected.bucketId : null;
  const metricId = chart.metric_id;
  const select = useMemo(() => (bucketId: string) => onSelect({ metricId, bucketId }), [onSelect, metricId]);
  const description =
    `${chart.title}: horizontal bars of ${plural(chart.total, "ticket", "tickets")} by ${chart.caption.toLowerCase()}, ` +
    `in whole days from Created to the as-of date ${asOf}. ` +
    chart.buckets.map((bucket) => `${bucket.label}: ${numberFormat.format(bucket.tickets)}`).join("; ") +
    ".";
  return (
    <article className="queue-chart" aria-labelledby={headingId}>
      <h4 id={headingId} tabIndex={-1}>
        {chart.title}
      </h4>
      <p className="chart-caption">
        <strong>{chart.caption}</strong>
        <span className="muted">
          {" "}
          · {chart.measured_on}, {asOf} · whole days
        </span>
      </p>
      <p className="chart-total num">{totalLine(chart)}</p>
      {chart.availability.status !== "available" ? (
        <p className="unresolved">{chart.availability.reason}</p>
      ) : chart.total === 0 ? (
        <p className="status">No {chart.population} tickets are inside these filters. Widen or clear the filters.</p>
      ) : (
        <HorizontalBarChart
          description={description}
          categoryTitle={chart.caption}
          valueTitle="Tickets"
          data={data}
          tableCaption={`${chart.title} by ${chart.caption.toLowerCase()}, as of ${asOf}`}
          onSelect={select}
          selectLabel={(datum) =>
            `Show the ${plural(datum.value, `${chart.population} ticket`, `${chart.population} tickets`)} aged ${datum.label}`
          }
          selectedKey={selectedKey}
          selectedNote={SELECTED_NOTE}
        />
      )}
      {chart.warnings.map((warning) => (
        <p key={warning} className="unresolved">
          {warning}
        </p>
      ))}
      <details className="chart-definition">
        <summary>How this is calculated</summary>
        <p>{chart.definition}</p>
        <p className="muted">
          Metric <code>{chart.metric_id}</code>, registry {registry}. Click a bar, or open View data and choose an age,
          to list its tickets.
        </p>
      </details>
    </article>
  );
}

interface DrilldownProps {
  state: Drilldown;
  chart: QueueChart | undefined;
  onOpen: OpenQueueTicket;
  onClose: () => void;
}

function DrilldownList({ state, chart, onOpen, onClose }: DrilldownProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  const bucket = chart?.buckets.find((item) => item.id === state.selection.bucketId);
  const ready = state.kind === "ready" ? state.data : null;

  // Focus moves to a newly opened bucket's list once, not on every refetch of the same one.
  const focused = useRef<Selection | null>(null);
  useEffect(() => {
    if (state.kind !== "ready" || focused.current === state.selection) return;
    focused.current = state.selection;
    heading.current?.focus();
  }, [state]);

  if (!chart || !bucket) return null;
  const matches = ready !== null && ready.tickets === bucket.tickets;
  return (
    <section className="queue-drill" aria-labelledby="queue-drill-heading">
      <div className="section-head">
        <h4 id="queue-drill-heading" ref={heading} tabIndex={-1}>
          {chart.title}, {bucket.label} since submission: {plural(bucket.tickets, "ticket", "tickets")}
        </h4>
        <button type="button" className="secondary" onClick={onClose}>
          Close list
        </button>
      </div>
      {state.kind === "loading" ? <p className="status">Loading the tickets…</p> : null}
      {state.kind === "failed" ? (
        <p className="notice notice-error" role="alert">
          The tickets could not be listed: {state.message}. Choose the bar again; if it still fails, reload the page.
        </p>
      ) : null}
      {ready ? (
        <>
          <p className="muted">
            {matches
              ? `Exactly the ${plural(ready.tickets, "ticket", "tickets")} in the bar`
              : `${plural(ready.tickets, "ticket", "tickets")}; the chart is updating`}
            , oldest first, under {ready.filters.description}, as of {ready.as_of.date}, Snapshot{" "}
            <code className="fingerprint">{ready.snapshot_fingerprint.slice(0, 12)}</code>, registry{" "}
            {ready.versions.registry}. Open a ticket to see its source row.
          </p>
          {ready.rows.length === 0 ? (
            <p className="status">No tickets are in this bucket under these filters.</p>
          ) : (
            <div className="table-scroll">
              <table>
                <caption className="visually-hidden">
                  {chart.title} aged {bucket.label} since submission, oldest first
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Ticket Number</th>
                    <th scope="col" className="numeric">
                      Excel row
                    </th>
                    <th scope="col">Employee</th>
                    <th scope="col">Date</th>
                    <th scope="col">Created</th>
                    <th scope="col" className="numeric">
                      Age since submission
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {ready.rows.map((row) => (
                    <tr key={row.excel_row}>
                      <th scope="row">
                        <button
                          type="button"
                          className="open-evidence"
                          aria-haspopup="dialog"
                          aria-label={`${chart.population} ticket ${row.ticket_number ?? `row ${row.excel_row}`}`}
                          onClick={(event) => onOpen(row, chart.population, ready.snapshot_fingerprint, event.currentTarget)}
                        >
                          {row.ticket_number ?? `Row ${row.excel_row}`}
                        </button>
                      </th>
                      <td className="numeric num">{row.excel_row}</td>
                      <td>{row.employee ?? <span className="muted">No employee</span>}</td>
                      <td className="num">{row.date ?? <span className="muted">not usable</span>}</td>
                      <td className="num">{timestamp(row.created)}</td>
                      <td className="numeric num">{days(row.value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}

interface ProcessingQueueProps {
  data: ProcessingQueueResponse;
  filters: FilterState;
  onOpen: OpenQueueTicket;
}

/**
 * Two separate age-since-submission bar charts, Pending and Approved but not Keyed, each with its table
 * alternative. Choosing a bar lists its tickets under the same filters, as-of date and Snapshot.
 */
export function ProcessingQueue({ data, filters, onOpen }: ProcessingQueueProps) {
  const [selection, setSelection] = useState<Selection | null>(null);
  const [drilldown, setDrilldown] = useState<Drilldown | null>(null);

  // Refetched with the charts, so a new filter or as-of date updates an open list in place.
  useEffect(() => {
    if (!selection) {
      setDrilldown(null);
      return;
    }
    const controller = new AbortController();
    setDrilldown((current) => (current && current.selection === selection ? current : { kind: "loading", selection }));
    fetchBucketTickets(selection.metricId, selection.bucketId, filters, controller.signal)
      .then((tickets) => setDrilldown({ kind: "ready", selection, data: tickets }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setDrilldown({ kind: "failed", selection, message: error instanceof Error ? error.message : String(error) });
      });
    return () => controller.abort();
  }, [selection, filters, data]);

  const select = useMemo(
    () => (next: Selection) =>
      setSelection((current) =>
        current && current.metricId === next.metricId && current.bucketId === next.bucketId ? current : next,
      ),
    [],
  );

  function close() {
    const opened = selection;
    setSelection(null);
    // Back to the chart the list came from.
    if (opened) document.getElementById(`queue-${opened.metricId}`)?.focus();
  }

  const selectedChart = data.charts.find((chart) => chart.metric_id === selection?.metricId);
  return (
    <section className="priorities queue" aria-labelledby="queue-heading">
      <h3 id="queue-heading" tabIndex={-1}>
        Processing queue
      </h3>
      <p className="muted">{data.note}</p>
      <p className="queue-context">
        <span className="muted">Grain </span>
        {data.grain}
        <span className="muted"> · Showing </span>
        {data.filters.description}
        <span className="muted"> · As of </span>
        <span className="num">{data.as_of.date}</span>
        <span className="muted"> ({data.as_of.is_default ? "assumed" : "set by the analyst"})</span>
      </p>
      <div className="queue-charts">
        {data.charts.map((chart) => (
          <QueueChartCard
            key={chart.metric_id}
            chart={chart}
            asOf={data.as_of.date}
            registry={data.versions.registry}
            selected={selection}
            onSelect={select}
          />
        ))}
      </div>
      {drilldown ? <DrilldownList state={drilldown} chart={selectedChart} onOpen={onOpen} onClose={close} /> : null}
    </section>
  );
}
