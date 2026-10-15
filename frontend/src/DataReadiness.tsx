import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import {
  fetchReadinessRows,
  type DataReadinessResponse,
  type DescriptionDateReference,
  type FilterState,
  type ReadinessAliasRow,
  type ReadinessCheck,
  type ReadinessCheckId,
  type ReadinessRowsResponse,
  type ReadinessTicketRow,
  type ReportingWindowState,
} from "./api";

/** Opens one listed Ticket on its own in the drawer; `opener` gets focus back when it closes. */
export type OpenReadinessTicket = (row: ReadinessTicketRow, fingerprint: string, opener: HTMLButtonElement) => void;
/** Opens the possible duplicate proposing an Alias, where it is confirmed or rejected. */
export type OpenReadinessAlias = (row: ReadinessAliasRow, fingerprint: string, opener: HTMLButtonElement) => void;

type Drilldown =
  | { kind: "loading"; checkId: ReadinessCheckId }
  | { kind: "ready"; checkId: ReadinessCheckId; data: ReadinessRowsResponse }
  | { kind: "failed"; checkId: ReadinessCheckId; message: string };

const numberFormat = new Intl.NumberFormat("en-GB");
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function plural(count: number, one: string, many: string): string {
  return `${numberFormat.format(count)} ${count === 1 ? one : many}`;
}

const SINGULAR: Record<string, string> = { tickets: "ticket", "proposed Aliases": "proposed Alias" };

/** "129 tickets", "1 proposed Alias": a count in its check's own unit. */
function counted(check: ReadinessCheck, count: number): string {
  return plural(count, SINGULAR[check.unit] ?? check.unit, check.unit);
}

function isAlias(row: ReadinessTicketRow | ReadinessAliasRow): row is ReadinessAliasRow {
  return "labels" in row;
}

function ticketName(row: { ticket_number: string | null; excel_row: number }): string {
  return row.ticket_number ?? `Row ${row.excel_row}`;
}

/** One date written in a description, with how it reads and whether it differs from Date. */
export function DescriptionReference({ reference }: { reference: DescriptionDateReference }) {
  return (
    <>
      <q className="cell-text">{reference.text}</q> reads as {reference.interpretation}
      {reference.differs_from_date === null
        ? " · not compared"
        : reference.differs_from_date
          ? " · differs from Date"
          : " · agrees with Date"}
      {reference.uncertain ? <span className="tag">uncertain</span> : null}
    </>
  );
}

const TICKET_COLUMNS: Record<Exclude<ReadinessCheckId, "unresolved_identity">, string> = {
  ambiguous_intervals: "Periods without AM/PM",
  anomalous_dates: "Dates outside the window, as recorded",
  description_date_conflicts: "Dates in the description",
  missing_rates: "Rate and claimed hours",
  missing_required_fields: "Empty required cells",
};

function TicketDetail({ checkId, row }: { checkId: ReadinessCheckId; row: ReadinessTicketRow }): ReactNode {
  const detail = row.detail;
  if (checkId === "ambiguous_intervals") {
    return (
      <>
        <span className="cell-text">{String(detail.time ?? "")}</span>
        <ul className="readiness-detail">
          {(detail.ambiguous_periods ?? []).map((period, index) => (
            <li key={index}>
              <span className="num">{period.text}</span>
              {period.plausible_reading ? (
                <>
                  {" "}
                  · assumed <span className="num">{`${period.plausible_reading.start}–${period.plausible_reading.end}`}</span>
                </>
              ) : (
                " · no reading"
              )}
              {period.flags.map((flag) => (
                <span key={flag} className="tag">
                  {flag.replace(/_/g, " ")}
                </span>
              ))}
            </li>
          ))}
        </ul>
      </>
    );
  }
  if (checkId === "anomalous_dates") {
    return (
      <ul className="readiness-detail">
        {(detail.outside ?? []).map((item) => (
          <li key={item.field}>
            {item.field} <span className="num">{item.value}</span>
          </li>
        ))}
      </ul>
    );
  }
  if (checkId === "description_date_conflicts") {
    return (
      <ul className="readiness-detail">
        {(detail.description_dates?.references ?? []).map((reference) => (
          <li key={reference.start}>
            <DescriptionReference reference={reference} />
          </li>
        ))}
      </ul>
    );
  }
  if (checkId === "missing_rates") {
    const hours = detail.claimed_hours;
    return (
      <>
        Rate {detail.rate?.raw_type === "blank" ? "blank" : `${String(detail.rate?.value ?? "")} (not a number)`} ·{" "}
        {hours === null || hours === undefined ? "hours not usable" : `${numberFormat.format(hours)} hours claimed`}
        {detail.positive_hours ? <span className="tag">labour unpriced</span> : null}
      </>
    );
  }
  return (
    <ul className="readiness-detail">
      {(detail.issues ?? []).map((issue, index) => (
        <li key={index}>{issue.message}</li>
      ))}
    </ul>
  );
}

interface DrilldownProps {
  state: Drilldown;
  check: ReadinessCheck | undefined;
  onOpenTicket: OpenReadinessTicket;
  onOpenAlias: OpenReadinessAlias;
  onClose: () => void;
}

function DrilldownList({ state, check, onOpenTicket, onOpenAlias, onClose }: DrilldownProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  const ready = state.kind === "ready" ? state.data : null;
  // Focus moves to a newly opened list once, not on every refetch of the same one.
  const focused = useRef<ReadinessCheckId | null>(null);
  useEffect(() => {
    if (state.kind !== "ready" || focused.current === state.checkId) return;
    focused.current = state.checkId;
    heading.current?.focus();
  }, [state]);

  if (!check || check.count === null) return null;
  const matches = ready !== null && ready.count === check.count;
  return (
    <section className="queue-drill readiness-drill" aria-labelledby="readiness-drill-heading">
      <div className="section-head">
        <h4 id="readiness-drill-heading" ref={heading} tabIndex={-1}>
          {check.label}: {counted(check, check.count)}
        </h4>
        <button type="button" className="secondary" onClick={onClose}>
          Close list
        </button>
      </div>
      <p className="muted">{check.definition}</p>
      {state.kind === "loading" ? <p className="status">Loading the list…</p> : null}
      {state.kind === "failed" ? (
        <p className="notice notice-error" role="alert">
          The list could not be loaded: {state.message}. Choose the count again; if it still fails, reload the page.
        </p>
      ) : null}
      {ready ? (
        <>
          <p className="muted">
            {matches ? `Exactly the ${counted(check, ready.count)} counted` : `${counted(check, ready.count)}; the count is updating`}
            {check.id === "unresolved_identity" ? "" : ", by Excel row"}, under {ready.filters.description}
            {check.id === "anomalous_dates" && ready.reporting_window
              ? `, reporting window ${ready.reporting_window.description}`
              : ""}
            , Snapshot <code className="fingerprint">{ready.snapshot_fingerprint.slice(0, 12)}</code>, registry{" "}
            {ready.versions.registry}, rules {ready.versions.rules}.
            {check.id === "unresolved_identity"
              ? " Open a proposal's possible duplicate to confirm or reject it."
              : " Open a ticket to see its source row."}
          </p>
          {check.summary ? <p className="unresolved">{check.summary}</p> : null}
          {ready.rows.length === 0 ? (
            <p className="status">Nothing to list under these filters.</p>
          ) : check.id === "unresolved_identity" ? (
            <div className="table-scroll">
              <table>
                <caption className="visually-hidden">{check.label}</caption>
                <thead>
                  <tr>
                    <th scope="col">Names as written</th>
                    <th scope="col">Proposed by</th>
                    <th scope="col">Decision</th>
                  </tr>
                </thead>
                <tbody>
                  {ready.rows.filter(isAlias).map((row) => (
                    <tr key={row.labels.join("|")}>
                      <th scope="row">
                        <button
                          type="button"
                          className="open-evidence"
                          aria-haspopup="dialog"
                          aria-label={`Decide whether ${row.names.join(" and ")} are one person`}
                          onClick={(event) => onOpenAlias(row, ready.snapshot_fingerprint, event.currentTarget)}
                        >
                          {row.names.join(" / ")}
                        </button>
                      </th>
                      <td>
                        {row.proposed_by
                          .map(
                            (pair) =>
                              `${pair.ticket_numbers.map((number, index) => number ?? `row ${pair.excel_rows[index]}`).join(" and ")}` +
                              ` (rows ${pair.excel_rows.join(" and ")})`,
                          )
                          .join("; ")}
                        {row.possible_duplicate ? <span className="muted"> · in {row.possible_duplicate}</span> : null}
                      </td>
                      <td>{row.decision.label}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="table-scroll">
              <table>
                <caption className="visually-hidden">{check.label}, by Excel row</caption>
                <thead>
                  <tr>
                    <th scope="col">Ticket Number</th>
                    <th scope="col" className="numeric">
                      Excel row
                    </th>
                    <th scope="col">Employee</th>
                    <th scope="col">Date</th>
                    <th scope="col">Status</th>
                    <th scope="col">{TICKET_COLUMNS[check.id]}</th>
                  </tr>
                </thead>
                <tbody>
                  {ready.rows.filter((row): row is ReadinessTicketRow => !isAlias(row)).map((row) => (
                    <tr key={row.excel_row}>
                      <th scope="row">
                        <button
                          type="button"
                          className="open-evidence"
                          aria-haspopup="dialog"
                          aria-label={`Ticket ${ticketName(row)}, ${check.label.toLowerCase()}`}
                          onClick={(event) => onOpenTicket(row, ready.snapshot_fingerprint, event.currentTarget)}
                        >
                          {ticketName(row)}
                        </button>
                      </th>
                      <td className="numeric num">{row.excel_row}</td>
                      <td>{row.employee ?? <span className="muted">No employee</span>}</td>
                      <td className="num">{row.date ?? <span className="muted">not usable</span>}</td>
                      <td>{row.status ?? <span className="muted">unreadable</span>}</td>
                      <td>
                        <TicketDetail checkId={check.id} row={row} />
                      </td>
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

interface WindowControlProps {
  data: DataReadinessResponse;
  reportingWindow: ReportingWindowState;
  onChange: (reportingWindow: ReportingWindowState) => void;
}

/** The visible reporting window: two inclusive dates, defaulting to the years Created covers. */
function WindowControl({ data, reportingWindow, onChange }: WindowControlProps) {
  const shown = data.reporting_window;
  const [from, setFrom] = useState(reportingWindow.from ?? shown?.from ?? "");
  const [to, setTo] = useState(reportingWindow.to ?? shown?.to ?? "");
  const [error, setError] = useState("");
  useEffect(() => {
    setFrom(shown?.from ?? "");
    setTo(shown?.to ?? "");
  }, [shown?.from, shown?.to]);

  function apply(event: FormEvent) {
    event.preventDefault();
    if (!ISO_DATE.test(from) || !ISO_DATE.test(to)) {
      setError("Give both dates in full.");
      return;
    }
    if (from > to) {
      setError("The window must start on or before its end.");
      return;
    }
    setError("");
    onChange({
      from: from === shown?.default_from ? null : from,
      to: to === shown?.default_to ? null : to,
    });
  }

  return (
    <form className="readiness-window" onSubmit={apply} aria-labelledby="readiness-window-legend">
      <p id="readiness-window-legend" className="readiness-window-title">
        Reporting window{" "}
        <span className="muted">
          {shown ? (shown.is_default ? "· default, the years Created covers" : "· set by the analyst") : "· not set"}
        </span>
      </p>
      <label>
        From
        <input type="date" value={from} onChange={(event) => setFrom(event.target.value)} />
      </label>
      <label>
        To
        <input type="date" value={to} onChange={(event) => setTo(event.target.value)} />
      </label>
      <button type="submit" className="secondary">
        Apply window
      </button>
      {shown && !shown.is_default ? (
        <button type="button" className="secondary" onClick={() => onChange({ from: null, to: null })}>
          Use the Created years
        </button>
      ) : null}
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      <p className="muted readiness-window-note">
        {shown ? `${shown.description}, both ends included; checks ${shown.dates_checked.join(", ")}. ` : ""}
        {shown?.note}
      </p>
    </form>
  );
}

interface DataReadinessProps {
  data: DataReadinessResponse;
  filters: FilterState;
  reportingWindow: ReportingWindowState;
  onWindowChange: (reportingWindow: ReportingWindowState) => void;
  onOpenTicket: OpenReadinessTicket;
  onOpenAlias: OpenReadinessAlias;
}

/**
 * Which records cannot be reliably compared or valued: compact counts, each a registry metric (or the Alias
 * proposals) under the filters, and each listing exactly the rows it counts.
 */
export function DataReadiness({
  data,
  filters,
  reportingWindow,
  onWindowChange,
  onOpenTicket,
  onOpenAlias,
}: DataReadinessProps) {
  const [selected, setSelected] = useState<ReadinessCheckId | null>(null);
  const [drilldown, setDrilldown] = useState<Drilldown | null>(null);

  // Refetched with the counts, so a new filter, window or review decision updates an open list in place.
  useEffect(() => {
    if (!selected) {
      setDrilldown(null);
      return;
    }
    const controller = new AbortController();
    setDrilldown((current) => (current && current.checkId === selected ? current : { kind: "loading", checkId: selected }));
    fetchReadinessRows(selected, filters, reportingWindow, controller.signal)
      .then((rows) => setDrilldown({ kind: "ready", checkId: selected, data: rows }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setDrilldown({ kind: "failed", checkId: selected, message: error instanceof Error ? error.message : String(error) });
      });
    return () => controller.abort();
  }, [selected, filters, reportingWindow, data]);

  function close() {
    const opened = selected;
    setSelected(null);
    if (opened) document.getElementById(`readiness-${opened}`)?.focus();
  }

  return (
    <section className="priorities readiness" aria-labelledby="readiness-heading">
      <h3 id="readiness-heading" tabIndex={-1}>
        {data.title}
      </h3>
      <p className="muted">
        {data.question} {data.note}
      </p>
      <p className="queue-context">
        <span className="muted">Showing </span>
        {data.filters.description}
      </p>
      <WindowControl data={data} reportingWindow={reportingWindow} onChange={onWindowChange} />
      <ul className="readiness-counts">
        {data.checks.map((check) => {
          const disabled = check.availability.status !== "available" || check.count === null;
          return (
            <li key={check.id} className={selected === check.id ? "readiness-count selected" : "readiness-count"}>
              <button
                type="button"
                id={`readiness-${check.id}`}
                aria-pressed={selected === check.id}
                disabled={disabled}
                aria-label={
                  disabled
                    ? `${check.label}: not available`
                    : `${check.label}: ${counted(check, check.count ?? 0)}. List them`
                }
                onClick={() => setSelected(check.id)}
              >
                <span className="tile-label">{check.label}</span>
                <span className="tile-value num">{check.count === null ? "—" : numberFormat.format(check.count)}</span>
                <span className="muted readiness-unit">{check.count === null ? "not available" : check.unit}</span>
              </button>
              <p className="readiness-description">{disabled ? check.availability.reason : check.description}</p>
              {check.summary && !disabled ? <p className="unresolved readiness-summary">{check.summary}</p> : null}
              {selected === check.id ? <p className="muted readiness-listed">Listed below</p> : null}
            </li>
          );
        })}
      </ul>
      {drilldown ? (
        <DrilldownList
          state={drilldown}
          check={data.checks.find((check) => check.id === drilldown.checkId)}
          onOpenTicket={onOpenTicket}
          onOpenAlias={onOpenAlias}
          onClose={close}
        />
      ) : null}
    </section>
  );
}
