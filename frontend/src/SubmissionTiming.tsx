import { useEffect, useMemo, useState } from "react";

import {
  fetchExploreCatalogue,
  fetchSubmissionTiming,
  type DrilldownRow,
  type ExploreCatalogue,
  type FilterState,
  type OverviewPlanChart,
  type PlanRequest,
  type SubmissionTimingResponse,
} from "./api";
import { stackedWeekBars, STATUS_COLOURS } from "./charts/templates";
import { VegaChart } from "./charts/VegaChart";
import { DrilldownPanel, ResultView } from "./Explore";

const numberFormat = new Intl.NumberFormat("en-GB");
const plural = (count: number, one: string, many: string) => `${numberFormat.format(count)} ${count === 1 ? one : many}`;

interface SubmissionTimingProps {
  filters: FilterState;
  /** Bumped when the Snapshot or as-of date changes. */
  generation: number;
  onOpenTicket: (row: DrilldownRow, fingerprint: string, opener: HTMLElement) => void;
}

type Loaded = { data: SubmissionTimingResponse; filters: FilterState };
/** The weekly segment or week total whose tickets are listed: its plan request and the week id. */
type Drill = { request: PlanRequest; week: string; label: string };

/**
 * Submission and review timing (ticket #34): weekly submissions stacked by current status, and the
 * submission-lag and approval-interval distributions. Every chart comes from fixed Explore plans run under
 * the Overview filters, so each segment, week and bin drills down through Explore's own drilldown.
 */
export function SubmissionTiming({ filters, generation, onOpenTicket }: SubmissionTimingProps) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [catalogue, setCatalogue] = useState<ExploreCatalogue | null>(null);
  const [error, setError] = useState("");
  const [drill, setDrill] = useState<Drill | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchExploreCatalogue(controller.signal)
      .then(setCatalogue)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => controller.abort();
  }, [generation]);

  useEffect(() => {
    const controller = new AbortController();
    fetchSubmissionTiming(filters, controller.signal)
      .then((data) => {
        setLoaded({ data, filters });
        setDrill(null);
        setError("");
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => controller.abort();
  }, [filters, generation]);

  const weekly = loaded?.data.weekly;
  const spec = useMemo(() => {
    if (!weekly) return null;
    const described = weekly.weeks
      .map((week) => `${week.label}: ${week.segments.map((segment) => `${segment.tickets} ${segment.status}`).join(", ")}`)
      .join("; ");
    return stackedWeekBars({
      description: `Stacked bars of ${plural(weekly.total, "ticket", "tickets")} by submission week and current status. ${described}.`,
      // "Week of 7 Sep 2026" reads as "7 Sep" under the axis title "Week starting".
      weeks: weekly.weeks.map((week) => ({ key: week.id, label: week.label.replace(/^Week of /, "").replace(/ \d{4}$/, ""), total: week.total })),
      statuses: weekly.statuses,
      segments: weekly.weeks.flatMap((week) =>
        week.segments.map((segment) => ({ key: `${week.id}|${segment.status}`, week: week.id, status: segment.status, value: segment.tickets })),
      ),
      selectable: true,
    });
  }, [weekly]);

  if (error) {
    return (
      <p className="notice notice-error" role="alert">
        Submission and review timing could not be loaded: {error}. Change the filters or reload the page.
      </p>
    );
  }
  if (!loaded || !catalogue || !weekly || !spec) return <p className="status">Loading submission and review timing…</p>;

  const { data } = loaded;
  const requestFor = (chart: OverviewPlanChart): PlanRequest => ({
    plan: chart.request.plan,
    inherited: loaded.filters,
    snapshotFingerprint: data.snapshot_fingerprint,
  });
  const weekLabel = (id: string) => weekly.weeks.find((week) => week.id === id)?.label ?? id;
  const openSegment = (weekId: string, status: string) => {
    const series = weekly.series.find((item) => item.status === status);
    if (series) setDrill({ request: requestFor(series), week: weekId, label: `${weekLabel(weekId)}, ${status}` });
  };
  const openWeek = (weekId: string) => setDrill({ request: requestFor(weekly.all), week: weekId, label: `${weekLabel(weekId)}, every status` });

  return (
    <section className="priorities timing" aria-labelledby="timing-heading">
      <h3 id="timing-heading" tabIndex={-1}>
        Submission and review timing
      </h3>
      <p>{data.question}</p>

      <section aria-labelledby="timing-weekly-heading">
        <h4 id="timing-weekly-heading">{weekly.title}</h4>
        <p className="muted">{weekly.caption}</p>
        <p className="active-filters">
          <span className="muted">Showing </span>
          {weekly.all.result.filters.description}
          <span className="muted"> · Grain </span>Ticket
          <span className="muted"> · </span>
          {plural(weekly.total, "ticket", "tickets")}
        </p>
        <ul className="status-legend" aria-label="Status colours">
          {weekly.statuses.map((status) => (
            <li key={status}>
              <span className="swatch" style={{ background: STATUS_COLOURS[status] }} aria-hidden="true" />
              {status}
            </li>
          ))}
        </ul>
        <figure className="bar-chart">
          <VegaChart
            spec={spec}
            onSelect={(key) => {
              const [weekId, status] = key.split("|");
              openSegment(weekId, status);
            }}
          />
          <details className="chart-data">
            <summary>View data</summary>
            <div className="table-scroll">
              <table>
                <caption>Tickets by submission week and current status; choose a count to list its tickets</caption>
                <thead>
                  <tr>
                    <th scope="col">Submitted</th>
                    {weekly.statuses.map((status) => (
                      <th key={status} scope="col" className="numeric">
                        {status}
                      </th>
                    ))}
                    <th scope="col" className="numeric">
                      Every status
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {weekly.weeks.map((week) => (
                    <tr key={week.id}>
                      <th scope="row">{week.label}</th>
                      {week.segments.map((segment) => (
                        <td key={segment.status} className="numeric">
                          {segment.tickets > 0 ? (
                            <button
                              type="button"
                              className="link-button"
                              aria-label={`List the ${plural(segment.tickets, "ticket", "tickets")} submitted in the ${week.label.toLowerCase()} and now ${segment.status}`}
                              onClick={() => openSegment(week.id, segment.status)}
                            >
                              {numberFormat.format(segment.tickets)}
                            </button>
                          ) : (
                            "0"
                          )}
                        </td>
                      ))}
                      <td className="numeric">
                        <button
                          type="button"
                          className="link-button"
                          aria-label={`List all ${plural(week.total, "ticket", "tickets")} submitted in the ${week.label.toLowerCase()}`}
                          onClick={() => openWeek(week.id)}
                        >
                          {numberFormat.format(week.total)}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </figure>
        {weekly.other_status_tickets > 0 ? (
          <p className="notice" role="note">
            {plural(weekly.other_status_tickets, "ticket has", "tickets have")} an Approval Status that is none of{" "}
            {weekly.statuses.join(", ")}; {weekly.other_status_tickets === 1 ? "it is" : "they are"} in the week totals but
            in no coloured segment.
          </p>
        ) : null}
        {weekly.hidden_weeks > 0 ? (
          <p className="notice" role="note">
            {plural(weekly.hidden_weeks, "earlier week is", "earlier weeks are")} not drawn; the chart shows at most 25.
          </p>
        ) : null}
        {drill ? (
          <DrilldownPanel
            request={drill.request}
            group={drill.week}
            headingId="timing-drilldown-heading"
            onClose={() => setDrill(null)}
            onOpenTicket={onOpenTicket}
          />
        ) : null}
      </section>

      {([
        ["lag", data.lag],
        ["interval", data.interval],
      ] as const).map(([id, chart]) => (
        <section key={id} className="explore-result" aria-labelledby={`timing-${id}-result-heading`}>
          <p className="muted">
            <strong>{chart.title}.</strong> {chart.note}
          </p>
          <ResultView
            result={chart.result}
            staleReason={null}
            catalogue={catalogue}
            request={requestFor(chart)}
            onRerun={() => undefined}
            onOpenTicket={onOpenTicket}
            idPrefix={`timing-${id}`}
          />
        </section>
      ))}
    </section>
  );
}
