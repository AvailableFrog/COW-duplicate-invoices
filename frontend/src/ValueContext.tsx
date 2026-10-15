import type { ExtraClaimGroup, ValueContextResponse, ValueFigure, ValueScenario } from "./api";

const money = new Intl.NumberFormat("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const numberFormat = new Intl.NumberFormat("en-GB");

/** How each figure's kind reads on screen; the flagged and hypothetical scenarios are never added together. */
const SCENARIO_LABELS: Record<ValueScenario, string> = {
  recorded: "As recorded",
  flagged: "Flagged by staff",
  hypothetical: "Hypothetical",
  analyst_reviewed: "Analyst-reviewed alternative",
};

function bbd(value: number | null): string {
  return value === null ? "Not available" : `BBD ${money.format(value)}`;
}

function plural(count: number, one: string, many: string): string {
  return `${numberFormat.format(count)} ${count === 1 ? one : many}`;
}

/** "122 Pending tickets", or "3 tickets (2 Pending, 1 Approved)" when the statuses are mixed. */
function ticketsByStatus(data: ValueContextResponse["unpriced_labour"]): string {
  const { statuses, tickets } = data;
  if (statuses.length === 1 && statuses[0].status) return plural(tickets, `${statuses[0].status} ticket`, `${statuses[0].status} tickets`);
  const detail = statuses.map((item) => `${numberFormat.format(item.tickets)} ${item.status ?? "unreadable status"}`).join(", ");
  return `${plural(tickets, "ticket", "tickets")} (${detail})`;
}

/** "116.24 each" when every ticket in the group has one base value, otherwise each value in turn. */
function perTicket(values: number[]): string {
  return values.every((value) => value === values[0])
    ? `${money.format(values[0])} each`
    : values.map((value) => money.format(value)).join(" / ");
}

/** The exact repeats behind the hypothetical figure, each with its tickets and the n − 1 extra claims valued. */
function ExtraClaimTable({ groups, figure }: { groups: ExtraClaimGroup[]; figure: ValueFigure }) {
  if (groups.length === 0) return null;
  return (
    <section className="value-groups" aria-labelledby="value-groups-heading">
      <h4 id="value-groups-heading">Behind the hypothetical figure: each exact repeat, not flagged</h4>
      <div className="table-scroll">
        <table>
          <caption className="visually-hidden">{figure.label}: each exact repeat, not flagged, and its extra claims</caption>
          <thead>
            <tr>
              <th scope="col">Exact repeat, not flagged</th>
              <th scope="col">Tickets</th>
              <th scope="col">Excel rows</th>
              <th scope="col" className="numeric">
                Base value per ticket
              </th>
              <th scope="col" className="numeric">
                Extra claims
              </th>
              <th scope="col" className="numeric">
                Hypothetical value
              </th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => (
              <tr key={group.excel_rows.join("+")}>
                <th scope="row">
                  {group.employee ?? "No employee"}
                  {group.examples.length > 0 ? <span className="muted"> · Example {group.examples.join(", ")}</span> : null}
                </th>
                <td className="num">
                  {group.ticket_numbers.map((number, index) => number ?? `row ${group.excel_rows[index]}`).join(", ")}
                </td>
                <td className="num">{group.excel_rows.join(", ")}</td>
                <td className="numeric num">{perTicket(group.ticket_values)}</td>
                <td className="numeric num">{group.extra_claims}</td>
                <td className="numeric num">{bbd(group.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function FigureCard({ figure, registry }: { figure: ValueFigure; registry: string }) {
  const headingId = `value-${figure.id}`;
  return (
    <article className={`value-figure value-${figure.scenario}`} aria-labelledby={headingId}>
      <p className="value-scenario">{SCENARIO_LABELS[figure.scenario]}</p>
      <h4 id={headingId}>{figure.label}</h4>
      <p className="value-amount num">{bbd(figure.value)}</p>
      <dl className="value-facts">
        <div>
          <dt>Formula</dt>
          <dd>{figure.formula}</dd>
        </div>
        <div>
          <dt>Interpretation</dt>
          <dd>{figure.interpretation}</dd>
        </div>
        <div>
          <dt>Completeness</dt>
          <dd>{figure.completeness}</dd>
        </div>
      </dl>
      <details className="chart-definition">
        <summary>Registry definition</summary>
        <p>{figure.definition}</p>
        <p className="muted">
          Metric <code>{figure.metric_id}</code>, registry {registry}, grain {figure.grain}. Its contributing Excel rows are
          listed by the metric request with <code>rows=true</code>.
        </p>
      </details>
    </article>
  );
}

/**
 * The value-context panel: three small BBD figures with formula, interpretation and completeness, collapsed by
 * default so money is never the headline. An analyst-reviewed alternative appears only when kept/replaced links exist.
 */
export function ValueContext({ data }: { data: ValueContextResponse }) {
  const unpriced = data.unpriced_labour;
  const alternative = data.reviewed_alternative;
  return (
    <section className="value-context" aria-labelledby="value-heading">
      <details>
        <summary>
          <h3 id="value-heading">Value context</h3>
          <span className="muted value-summary-note">
            Three {data.currency} figures with their formulas and completeness
          </span>
        </summary>
        <p className="muted value-note">{data.note}</p>
        <p className="queue-context">
          <span className="muted">Currency </span>
          {data.currency} (Barbados dollars)
          <span className="muted"> · Showing </span>
          {data.filters.description}
          <span className="muted"> · Snapshot </span>
          <code className="fingerprint">{data.snapshot_fingerprint.slice(0, 12)}</code>
          <span className="muted"> · Registry </span>
          {data.versions.registry}
        </p>
        <p className={unpriced.tickets > 0 ? "unresolved value-unpriced" : "muted value-unpriced"}>
          {unpriced.tickets > 0 ? (
            <>
              <strong>Unpriced labour:</strong> {numberFormat.format(unpriced.hours)} hours across {ticketsByStatus(unpriced)}{" "}
              with no Rate. That labour's value is unknown, not zero, and is left out of every figure below; any Job Work
              Pay on those tickets is included.
            </>
          ) : (
            "Every ticket's labour inside these filters is priced."
          )}
        </p>
        <div className="value-figures">
          {data.figures.map((figure) => (
            <FigureCard key={figure.id} figure={figure} registry={data.versions.registry} />
          ))}
        </div>
        {data.figures.map((figure) =>
          figure.possible_duplicates ? (
            <ExtraClaimTable key={figure.id} groups={figure.possible_duplicates} figure={figure} />
          ) : null,
        )}
        {alternative ? (
          <div className="value-reviewed">
            <FigureCard figure={alternative} registry={data.versions.registry} />
          </div>
        ) : (
          <p className="muted value-reviewed-none">
            No analyst-reviewed alternative: no reviewer has linked a replaced ticket to a kept one. Review Outcomes and
            notes alone never change these figures.
          </p>
        )}
      </details>
    </section>
  );
}
