import { useEffect, useMemo, useRef, useState } from "react";

import {
  executePlan,
  fetchExploreCatalogue,
  PlanRejected,
  StaleSnapshot,
  type ChartTemplateId,
  type DateBasis,
  type ExploreCatalogue,
  type ExploreField,
  type FieldValue,
  type FilterState,
  type HeaderResponse,
  type Plan,
  type PlanFilter,
  type PlanIssue,
  type PlanOperator,
  type PlanResult,
  type PlanSort,
} from "./api";
import { TemplateChart } from "./charts/TemplateChart";

const numberFormat = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });

/** Where the plan's inherited filters come from: a copy of the Overview filters taken when chosen, or none. */
type Start = { kind: "overview"; filters: FilterState } | { kind: "all" };

type Run =
  | { kind: "idle" }
  | { kind: "running"; previous: PlanResult | null }
  | { kind: "ready"; result: PlanResult }
  | { kind: "rejected"; message: string; issues: PlanIssue[] }
  | { kind: "stale_header"; message: string }
  | { kind: "failed"; message: string; previous: PlanResult | null };

interface ExploreProps {
  header: HeaderResponse;
  /** The Overview filter bar as it stands now; copied only when the consultant chooses to use it. */
  overviewFilters: FilterState;
}

/** The Overview filters in words, as the Overview's own filter line reads. */
export function describeFilterState(filters: FilterState, dateBasisLabel: (id: DateBasis) => string): string {
  const parts: string[] = [];
  if (filters.dateFrom || filters.dateTo) {
    parts.push(
      `${dateBasisLabel(filters.dateBasis)} from ${filters.dateFrom ?? "the earliest date"} to ${filters.dateTo ?? "the latest date"}`,
    );
  } else {
    parts.push("all dates");
  }
  if (filters.job !== null) parts.push(`Job Number ${filters.job}`);
  if (filters.status !== null) parts.push(`Approval Status ${filters.status}`);
  return parts.join("; ");
}

function sameFilters(a: FilterState, b: FilterState): boolean {
  return (
    a.dateBasis === b.dateBasis && a.dateFrom === b.dateFrom && a.dateTo === b.dateTo && a.job === b.job && a.status === b.status
  );
}

function samePlan(a: Plan, b: Plan): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** The Explore tab: starter questions, editable chips compiled to a validated plan, and its chart and table. */
export function Explore({ header, overviewFilters }: ExploreProps) {
  const [catalogue, setCatalogue] = useState<ExploreCatalogue | null>(null);
  const [catalogueError, setCatalogueError] = useState("");
  const [start, setStart] = useState<Start | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [run, setRun] = useState<Run>({ kind: "idle" });
  // Bumped by Rerun: a new Snapshot never reruns a plan by itself, so a displayed result stays marked until then.
  const [rerun, setRerun] = useState(0);
  const fingerprint = useRef(header.snapshot_fingerprint);
  fingerprint.current = header.snapshot_fingerprint;

  useEffect(() => {
    const controller = new AbortController();
    fetchExploreCatalogue(controller.signal)
      .then((data) => {
        setCatalogue(data);
        setCatalogueError("");
        setPlan((current) => current ?? data.starters[0].plan);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setCatalogueError(error instanceof Error ? error.message : String(error));
      });
    return () => controller.abort();
  }, [header.snapshot_fingerprint]);

  useEffect(() => {
    if (!plan || !start) return;
    const controller = new AbortController();
    setRun((current) => ({ kind: "running", previous: shownResult(current) }));
    executePlan(plan, start.kind === "overview" ? start.filters : null, fingerprint.current, controller.signal)
      .then((result) => setRun({ kind: "ready", result }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof StaleSnapshot) setRun({ kind: "stale_header", message: error.message });
        else if (error instanceof PlanRejected) setRun({ kind: "rejected", message: error.message, issues: error.issues });
        else
          setRun((current) => ({
            kind: "failed",
            message: error instanceof Error ? error.message : String(error),
            previous: shownResult(current),
          }));
      });
    return () => controller.abort();
  }, [plan, start, rerun]);

  const dateBasisLabel = (id: DateBasis) => catalogue?.date_bases.find((basis) => basis.id === id)?.label ?? id;
  const overviewNow = describeFilterState(overviewFilters, dateBasisLabel);
  const result = shownResult(run);
  const staleResult =
    result !== null && (result.snapshot_fingerprint !== header.snapshot_fingerprint || result.as_of.date !== header.as_of.date);

  function choose(kind: Start["kind"]) {
    setStart(kind === "overview" ? { kind, filters: overviewFilters } : { kind });
  }

  return (
    <section aria-labelledby="explore-heading" className="explore">
      <h2 id="explore-heading">Explore</h2>
      <p className="explore-intro">
        Build a chart from the chips below. Each chip is part of a plan the service checks before running; every number
        comes from the metric registry, and there is no prompt field or model in this release.
      </p>

      <fieldset className="explore-start">
        <legend>Starting filters</legend>
        <label className="start-choice">
          <input
            type="radio"
            name="explore-start"
            checked={start?.kind === "overview"}
            onChange={() => choose("overview")}
          />
          <span>
            <strong>Use Overview filters</strong>
            <span className="muted"> · now {overviewNow}</span>
          </span>
        </label>
        <label className="start-choice">
          <input type="radio" name="explore-start" checked={start?.kind === "all"} onChange={() => choose("all")} />
          <span>
            <strong>Start with all data</strong>
            <span className="muted"> · no Overview filter, job or date basis is carried over</span>
          </span>
        </label>
      </fieldset>
      <p className="start-shown" role="status">
        {start === null
          ? "Choose how to start: the Overview filters are never applied here unless you choose them."
          : start.kind === "all"
            ? "Starting from all data. Only the chips below filter the chart."
            : `Starting from the Overview filters: ${describeFilterState(start.filters, dateBasisLabel)}. They apply beside the chips.`}
      </p>
      {start?.kind === "overview" && !sameFilters(start.filters, overviewFilters) ? (
        <p className="unresolved">
          The Overview filters have changed since you chose them (now {overviewNow}); this chart still uses the earlier
          ones.{" "}
          <button type="button" className="secondary" onClick={() => choose("overview")}>
            Use the current Overview filters
          </button>
        </p>
      ) : null}

      {catalogueError ? (
        <p className="notice notice-error" role="alert">
          The Explore choices could not be loaded: {catalogueError}. Reload the page.
        </p>
      ) : !catalogue || !plan ? (
        <p className="status">Loading the Explore choices…</p>
      ) : start === null ? null : (
        <>
          <Starters catalogue={catalogue} plan={plan} onChoose={setPlan} />
          <Chips catalogue={catalogue} plan={plan} onChange={setPlan} issues={run.kind === "rejected" ? run.issues : []} />
          <ResultPanel
            run={run}
            result={result}
            stale={staleResult}
            catalogue={catalogue}
            activeFingerprint={header.snapshot_fingerprint}
            onRerun={() => setRerun((value) => value + 1)}
          />
        </>
      )}
    </section>
  );
}

function shownResult(run: Run): PlanResult | null {
  if (run.kind === "ready") return run.result;
  if (run.kind === "running" || run.kind === "failed") return run.previous;
  return null;
}

function Starters({ catalogue, plan, onChoose }: { catalogue: ExploreCatalogue; plan: Plan; onChoose: (plan: Plan) => void }) {
  return (
    <section className="explore-starters" aria-labelledby="starters-heading">
      <h3 id="starters-heading">Starter questions</h3>
      <ul>
        {catalogue.starters.map((starter) => (
          <li key={starter.id}>
            <button
              type="button"
              className="starter"
              aria-pressed={samePlan(starter.plan, plan)}
              onClick={() => onChoose(starter.plan)}
            >
              {starter.question}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function valueText(value: FieldValue): string {
  return typeof value === "boolean" ? (value ? "true" : "false") : String(value);
}

function parseValue(field: ExploreField, text: string): FieldValue {
  if (field.kind === "boolean") return text === "true";
  if (field.kind === "integer") return Number(text);
  return text;
}

function defaultFilter(field: ExploreField): PlanFilter {
  return { field: field.id, operator: "eq", value: field.values[0]?.value ?? "" };
}

interface ChipsProps {
  catalogue: ExploreCatalogue;
  plan: Plan;
  onChange: (plan: Plan) => void;
  issues: PlanIssue[];
}

/** The editable chips; each change compiles to a new plan, which runs at once. */
function Chips({ catalogue, plan, onChange, issues }: ChipsProps) {
  const set = (patch: Partial<Plan>) => onChange({ ...plan, ...patch });
  const metric = catalogue.metrics.find((item) => item.id === plan.metric_id);
  const fields = catalogue.fields.filter((field) => field.available);
  const dimensions = fields.filter((field) => metric?.allowed_dimensions.includes(field.id) ?? true);
  const fieldById = (id: string) => catalogue.fields.find((field) => field.id === id);
  const operatorLabel = (id: PlanOperator) => catalogue.operators.find((operator) => operator.id === id)?.label ?? id;

  function setFilter(index: number, filter: PlanFilter) {
    set({ filters: plan.filters.map((item, position) => (position === index ? filter : item)) });
  }

  function changeMetric(metricId: string) {
    const next = catalogue.metrics.find((item) => item.id === metricId);
    const groupBy = plan.group_by.filter((name) => next?.allowed_dimensions.includes(name));
    set({ metric_id: metricId, group_by: groupBy });
  }

  return (
    <form className="chips" aria-label="Chart chips" onSubmit={(event) => event.preventDefault()}>
      <div className="chip-row">
        <label className="chip">
          <span>Metric</span>
          <select value={plan.metric_id} onChange={(event) => changeMetric(event.target.value)}>
            {catalogue.metrics.map((item) => (
              <option key={item.id} value={item.id} disabled={item.availability.status !== "available"}>
                {item.label} ({item.statistic} of {item.unit})
              </option>
            ))}
          </select>
        </label>
        <label className="chip">
          <span>Group by</span>
          <select
            value={plan.group_by[0] ?? ""}
            onChange={(event) => set({ group_by: event.target.value ? [event.target.value] : [] })}
          >
            <option value="">No grouping (one total)</option>
            {dimensions.map((field) => (
              <option key={field.id} value={field.id}>
                {field.id}
              </option>
            ))}
          </select>
        </label>
        <label className="chip">
          <span>Chart</span>
          <select value={plan.chart} onChange={(event) => set({ chart: event.target.value as ChartTemplateId })}>
            {catalogue.charts.map((chart) => (
              <option key={chart.id} value={chart.id}>
                {chart.label}
              </option>
            ))}
          </select>
        </label>
        <label className="chip">
          <span>Sort</span>
          <select value={plan.sort} onChange={(event) => set({ sort: event.target.value as PlanSort })}>
            {catalogue.sorts.map((sort) => (
              <option key={sort.id} value={sort.id}>
                {sort.label}
              </option>
            ))}
          </select>
        </label>
        <label className="chip">
          <span>Bars</span>
          <input
            type="number"
            min={catalogue.limits.min}
            max={catalogue.limits.max}
            value={plan.limit}
            onChange={(event) => {
              const limit = Math.round(Number(event.target.value));
              if (Number.isFinite(limit) && limit >= catalogue.limits.min && limit <= catalogue.limits.max) set({ limit });
            }}
          />
        </label>
        <label className="chip chip-check">
          <input type="checkbox" checked={plan.include_other} onChange={(event) => set({ include_other: event.target.checked })} />
          <span>Combine the rest as Other</span>
        </label>
      </div>

      <div className="chip-row">
        <label className="chip">
          <span>Date basis</span>
          <select value={plan.date_basis} onChange={(event) => set({ date_basis: event.target.value as DateBasis })}>
            {catalogue.date_bases.map((basis) => (
              <option key={basis.id} value={basis.id} disabled={!basis.available}>
                {basis.label}
              </option>
            ))}
          </select>
        </label>
        <label className="chip">
          <span>From</span>
          <input
            type="date"
            value={plan.date_range?.from ?? ""}
            onChange={(event) => {
              const from = event.target.value || null;
              const to = plan.date_range?.to ?? null;
              set({ date_range: from || to ? { from, to } : null });
            }}
          />
        </label>
        <label className="chip">
          <span>To</span>
          <input
            type="date"
            value={plan.date_range?.to ?? ""}
            onChange={(event) => {
              const to = event.target.value || null;
              const from = plan.date_range?.from ?? null;
              set({ date_range: from || to ? { from, to } : null });
            }}
          />
        </label>
        <p className="chip-note muted">
          {plan.date_range
            ? `The range applies to ${catalogue.date_bases.find((basis) => basis.id === plan.date_basis)?.label ?? plan.date_basis}.`
            : "All dates: the date basis applies once a range is set."}
        </p>
      </div>

      <fieldset className="chip-filters">
        <legend>Filters</legend>
        {plan.filters.length === 0 ? <p className="muted">No filters: every ticket in the starting filters counts.</p> : null}
        <ul>
          {plan.filters.map((filter, index) => {
            const field = fieldById(filter.field);
            const listed = filter.operator === "in" || filter.operator === "not_in";
            const values = Array.isArray(filter.value) ? filter.value : [filter.value];
            const name = `Filter ${index + 1}`;
            return (
              <li key={index} className="chip-filter" role="group" aria-label={name}>
                <label>
                  <span className="visually-hidden">{name} field</span>
                  <select
                    value={filter.field}
                    onChange={(event) => {
                      const next = fieldById(event.target.value);
                      if (next) setFilter(index, defaultFilter(next));
                    }}
                  >
                    {fields.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.id}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span className="visually-hidden">{name} operator</span>
                  <select
                    value={filter.operator}
                    onChange={(event) => {
                      const operator = event.target.value as PlanOperator;
                      const toList = operator === "in" || operator === "not_in";
                      setFilter(index, { ...filter, operator, value: toList ? values : values[0] });
                    }}
                  >
                    {(field?.operators ?? []).map((operator) => (
                      <option key={operator} value={operator}>
                        {operatorLabel(operator)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span className="visually-hidden">{name} value</span>
                  <select
                    multiple={listed}
                    value={listed ? values.map(valueText) : valueText(values[0] ?? "")}
                    onChange={(event) => {
                      if (!field) return;
                      const chosen = Array.from(event.target.selectedOptions, (option) => parseValue(field, option.value));
                      setFilter(index, { ...filter, value: listed ? chosen : chosen[0] });
                    }}
                  >
                    {(field?.values ?? []).map((item) => (
                      <option key={valueText(item.value)} value={valueText(item.value)}>
                        {item.label} ({numberFormat.format(item.tickets)})
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="secondary"
                  aria-label={`Remove filter ${index + 1}: ${filter.field} ${operatorLabel(filter.operator)} ${values.map(valueText).join(", ")}`}
                  onClick={() => set({ filters: plan.filters.filter((_, position) => position !== index) })}
                >
                  Remove
                </button>
              </li>
            );
          })}
        </ul>
        {plan.filters.length < catalogue.max_filters && fields.length > 0 ? (
          <button type="button" className="secondary" onClick={() => set({ filters: [...plan.filters, defaultFilter(fields[0])] })}>
            Add a filter
          </button>
        ) : null}
      </fieldset>

      {issues.length ? (
        <div className="notice notice-error" role="alert">
          <p>The plan was not run. Change these chips:</p>
          <ul>
            {issues.map((issue) => (
              <li key={`${issue.field}-${issue.code}`}>
                <strong>{issue.field}</strong>: {issue.message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </form>
  );
}

interface ResultPanelProps {
  run: Run;
  result: PlanResult | null;
  stale: boolean;
  catalogue: ExploreCatalogue;
  activeFingerprint: string;
  onRerun: () => void;
}

function ResultPanel({ run, result, stale, catalogue, activeFingerprint, onRerun }: ResultPanelProps) {
  const busy = run.kind === "running";
  if (run.kind === "stale_header") {
    return (
      <p className="notice notice-error" role="alert">
        {run.message} Reload the page to see the active Snapshot.
      </p>
    );
  }
  return (
    <section className="explore-result" aria-labelledby="explore-result-heading" aria-busy={busy}>
      <p className="status" role="status">
        {busy ? "Running the plan…" : ""}
      </p>
      {run.kind === "failed" ? (
        <p className="notice notice-error" role="alert">
          The plan could not be run: {run.message}. Change a chip to try again, or reload the page.
        </p>
      ) : null}
      {result ? (
        <ResultView result={result} stale={stale} catalogue={catalogue} activeFingerprint={activeFingerprint} onRerun={onRerun} />
      ) : null}
    </section>
  );
}

interface ResultViewProps {
  result: PlanResult;
  stale: boolean;
  catalogue: ExploreCatalogue;
  activeFingerprint: string;
  onRerun: () => void;
}

function ResultView({ result, stale, catalogue, activeFingerprint, onRerun }: ResultViewProps) {
  const dimension = result.plan.group_by[0] ?? null;
  const nouns = catalogue.fields.find((field) => field.id === dimension)?.nouns ?? ["group", "groups"];
  const total = result.result.total;
  const totalLine =
    total === null
      ? "No value"
      : result.metric.statistic === "count"
        ? `${numberFormat.format(total)} ${result.metric.unit}`
        : `${numberFormat.format(total)} ${result.metric.unit} over ${numberFormat.format(result.result.contributing_tickets)} tickets`;
  const table = useMemo(() => <ResultTable result={result} dimension={dimension} nouns={nouns} />, [result, dimension, nouns]);
  return (
    <>
      <h3 id="explore-result-heading">{result.title}</h3>
      <p className="explore-summary">{result.summary}</p>
      <p className="active-filters explore-context">
        <span className="muted">Showing </span>
        {result.filters.description}
        <span className="muted"> · Grain </span>
        {result.grain}
        <span className="muted"> · Starting filters </span>
        {result.inherited_filters.label}
        {result.inherited_filters.filters ? ` (${result.inherited_filters.filters.description})` : ""}
      </p>
      <p className="explore-provenance muted">
        Snapshot <span className="fingerprint">{result.snapshot_fingerprint.slice(0, 12)}</span> · as of {result.as_of.date}
        {result.as_of.is_assumption ? " (assumption)" : ""} · registry {result.versions.registry} · rules {result.versions.rules} ·
        parser {result.versions.parser}
      </p>
      {stale ? (
        <div className="notice notice-error" role="alert">
          <p>
            {result.snapshot_fingerprint !== activeFingerprint
              ? `This chart was made from Snapshot ${result.snapshot_fingerprint.slice(0, 12)}, and Snapshot ${activeFingerprint.slice(0, 12)} is now active.`
              : "The as-of date has changed since this chart was made."}{" "}
            Its numbers are withdrawn until you run the plan again.
          </p>
          <button type="button" className="primary-action" onClick={onRerun}>
            Rerun the plan
          </button>
        </div>
      ) : (
        <>
          <p className="chart-total num">{totalLine}</p>
          {result.availability.status !== "available" ? (
            <p className="unresolved">{result.availability.reason}</p>
          ) : result.chart === null ? (
            <p className="status">No tickets match this plan. Remove a filter or widen the date range.</p>
          ) : (
            <TemplateChart template={result.chart.template} spec={result.chart.spec} table={table} />
          )}
          {result.warnings.map((warning) => (
            <p key={warning} className="unresolved">
              {warning}
            </p>
          ))}
          {result.notes.map((note) => (
            <p key={note} className="muted">
              {note}
            </p>
          ))}
        </>
      )}
    </>
  );
}

function ResultTable({ result, dimension, nouns }: { result: PlanResult; dimension: string | null; nouns: [string, string] }) {
  const { groups, other, value_title: valueTitle } = result.result;
  // A count's value is its tickets; a sum also says how many tickets it adds up.
  const counted = result.metric.statistic !== "count";
  return (
    <div className="table-scroll">
      <table>
        <caption>
          {result.title}, {result.filters.description}: every {dimension ? nouns[0] : "total"}, including any combined as
          Other
        </caption>
        <thead>
          <tr>
            <th scope="col">{dimension ?? "Plan"}</th>
            <th scope="col" className="numeric">
              {valueTitle}
            </th>
            {counted ? (
              <th scope="col" className="numeric">
                Tickets
              </th>
            ) : null}
            <th scope="col">In the chart</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <tr key={group.id}>
              <th scope="row">{group.label}</th>
              <td className="numeric num">{numberFormat.format(group.value)}</td>
              {counted ? <td className="numeric num">{numberFormat.format(group.contributing_tickets)}</td> : null}
              <td>{group.shown ? "Own bar" : group.in_other ? "In Other" : "Not drawn"}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          {other ? (
            <tr>
              <th scope="row">{other.label}</th>
              <td className="numeric num">{numberFormat.format(other.value)}</td>
              {counted ? <td className="numeric num">{numberFormat.format(other.contributing_tickets)}</td> : null}
              <td>Bar for the rows marked In Other</td>
            </tr>
          ) : null}
          <tr>
            <th scope="row">Total</th>
            <td className="numeric num">{result.result.total === null ? "—" : numberFormat.format(result.result.total)}</td>
            {counted ? <td className="numeric num">{numberFormat.format(result.result.contributing_tickets)}</td> : null}
            <td />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
