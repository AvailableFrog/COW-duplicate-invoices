import { useEffect, useMemo, useRef, useState } from "react";

import {
  downloadCsv,
  executePlan,
  fetchDrilldown,
  fetchExploreCatalogue,
  PlanRejected,
  StaleSnapshot,
  type ChartTemplateId,
  type DateBasis,
  type DrilldownResult,
  type DrilldownRow,
  type ExploreCatalogue,
  type ExploreField,
  type FieldValue,
  type FilterState,
  type HeaderResponse,
  type HowCalculated,
  type Plan,
  type PlanFilter,
  type PlanForm,
  type PlanIssue,
  type PlanOperator,
  type PlanRequest,
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
  /** Bumped after every review save; a result made before one is withdrawn until rerun. */
  reviewGeneration: number;
  /** Open one Ticket's evidence in the drawer, from a drilldown row. */
  onOpenTicket: (row: DrilldownRow, fingerprint: string, opener: HTMLElement) => void;
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

/** What a plan draws, as the service decides it (plans.Plan.form). */
function formOf(plan: Plan, catalogue: ExploreCatalogue): PlanForm {
  const metric = catalogue.metrics.find((item) => item.id === plan.metric_id);
  if (metric?.distribution) return "distribution";
  if (plan.chart === "scatter") return "pair";
  const grouping = plan.group_by[0];
  if (grouping && catalogue.time_groupings.some((time) => time.id === grouping)) return "dates";
  return grouping ? "categories" : "total";
}

function isTimeGrouping(id: string | undefined, catalogue: ExploreCatalogue): boolean {
  return id !== undefined && catalogue.time_groupings.some((time) => time.id === id);
}

/**
 * Keep the chips a plan the service can run after one of them changed: a distribution has no grouping and is a
 * histogram or table, a line needs a week or month, a scatterplot a registry pair and no grouping, and an ordered
 * chart keeps its axis order with no Other. Every adjustment shows in the chips themselves.
 */
function conform(plan: Plan, catalogue: ExploreCatalogue, previous: Plan): Plan {
  const metric = catalogue.metrics.find((item) => item.id === plan.metric_id);
  const next: Plan = { ...plan };
  const pairable = catalogue.scatter_pairs.some((pair) => pair.metric_id === plan.metric_id);
  if (metric?.distribution) {
    next.group_by = [];
    if (next.chart !== "histogram" && next.chart !== "table") next.chart = "histogram";
  } else {
    if (next.chart === "scatter" && !pairable) next.chart = "bar_horizontal";
    if (next.chart === "scatter") next.group_by = [];
    const timed = isTimeGrouping(next.group_by[0], catalogue);
    if (next.chart === "histogram") next.chart = timed ? "line" : "bar_vertical";
    if (next.chart === "line" && !timed) next.chart = "bar_vertical";
  }
  const ordered = (plan: Plan) =>
    Boolean(catalogue.metrics.find((item) => item.id === plan.metric_id)?.distribution) ||
    isTimeGrouping(plan.group_by[0], catalogue) ||
    plan.chart === "scatter";
  if (ordered(next)) {
    next.sort = catalogue.ordered_sort;
    next.include_other = false;
  } else if (ordered(previous)) {
    // Back to categories: the usual largest-first bars with Other.
    next.sort = "metric_desc";
    next.include_other = true;
  }
  return next;
}

/** The Explore tab: starter questions, editable chips compiled to a validated plan, and its chart and table. */
export function Explore({ header, overviewFilters, reviewGeneration, onOpenTicket }: ExploreProps) {
  const [catalogue, setCatalogue] = useState<ExploreCatalogue | null>(null);
  const [catalogueError, setCatalogueError] = useState("");
  const [start, setStart] = useState<Start | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [run, setRun] = useState<Run>({ kind: "idle" });
  // Bumped by Rerun: a new Snapshot never reruns a plan by itself, so a displayed result stays marked until then.
  const [rerun, setRerun] = useState(0);
  const fingerprint = useRef(header.snapshot_fingerprint);
  fingerprint.current = header.snapshot_fingerprint;
  const review = useRef(reviewGeneration);
  review.current = reviewGeneration;
  // The review generation each displayed result was made under.
  const [resultReview, setResultReview] = useState(reviewGeneration);

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
    const madeUnder = review.current;
    executePlan(plan, start.kind === "overview" ? start.filters : null, fingerprint.current, controller.signal)
      .then((result) => {
        setResultReview(madeUnder);
        setRun({ kind: "ready", result });
      })
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
  // The request the displayed result answers, kept stable so its drilldown is fetched once per result.
  const request = useMemo<PlanRequest | null>(
    () =>
      result && start
        ? {
            plan: result.plan,
            inherited: start.kind === "overview" ? start.filters : null,
            snapshotFingerprint: result.snapshot_fingerprint,
          }
        : null,
    [result, start],
  );
  const staleReason =
    result === null
      ? null
      : result.snapshot_fingerprint !== header.snapshot_fingerprint
        ? `This chart was made from Snapshot ${result.snapshot_fingerprint.slice(0, 12)}, and Snapshot ${header.snapshot_fingerprint.slice(0, 12)} is now active.`
        : result.as_of.date !== header.as_of.date
          ? "The as-of date has changed since this chart was made."
          : resultReview !== reviewGeneration
            ? "A review decision was saved since this chart was made."
            : null;

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
          <Chips catalogue={catalogue} plan={plan} asOf={header.as_of.date} onChange={setPlan} issues={run.kind === "rejected" ? run.issues : []} />
          <ResultPanel
            run={run}
            result={result}
            staleReason={staleReason}
            catalogue={catalogue}
            request={request}
            onRerun={() => setRerun((value) => value + 1)}
            onOpenTicket={onOpenTicket}
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
  /** The analytical as-of date: where a new fixed range ends until the consultant changes it. */
  asOf: string;
  onChange: (plan: Plan) => void;
  issues: PlanIssue[];
}

/** The editable chips; each change compiles to a new plan, which runs at once. */
function Chips({ catalogue, plan, asOf, onChange, issues }: ChipsProps) {
  const set = (patch: Partial<Plan>) => onChange(conform({ ...plan, ...patch }, catalogue, plan));
  const metric = catalogue.metrics.find((item) => item.id === plan.metric_id);
  const fields = catalogue.fields.filter((field) => field.available);
  const dimensions = metric?.distribution ? [] : fields.filter((field) => metric?.allowed_dimensions.includes(field.id) ?? true);
  const fieldById = (id: string) => catalogue.fields.find((field) => field.id === id);
  const operatorLabel = (id: PlanOperator) => catalogue.operators.find((operator) => operator.id === id)?.label ?? id;
  const form = formOf(plan, catalogue);
  const pairable = catalogue.scatter_pairs.some((pair) => pair.metric_id === plan.metric_id);
  const ordered = form === "dates" || form === "distribution" || form === "pair";
  const relative = plan.date_range && "relative" in plan.date_range ? plan.date_range.relative : null;
  const fixed = plan.date_range && !("relative" in plan.date_range) ? plan.date_range : null;
  const rangeChoice = relative ?? (fixed ? "fixed" : "");

  function setFilter(index: number, filter: PlanFilter) {
    set({ filters: plan.filters.map((item, position) => (position === index ? filter : item)) });
  }

  function changeMetric(metricId: string) {
    const next = catalogue.metrics.find((item) => item.id === metricId);
    const groupBy = plan.group_by.filter(
      (name) => next?.allowed_dimensions.includes(name) || isTimeGrouping(name, catalogue),
    );
    set({ metric_id: metricId, group_by: groupBy });
  }

  /** Whether a chart can draw this plan, or would once its grouping is cleared (a scatterplot). */
  function chartFits(chart: ChartTemplateId): boolean {
    if (chart === "scatter") return pairable && !metric?.distribution;
    const forms = catalogue.charts.find((item) => item.id === chart)?.forms ?? [];
    return forms.includes(form === "pair" ? (plan.group_by.length ? "categories" : "total") : form);
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
            <option value="">{metric?.distribution ? "No grouping" : "No grouping (one total)"}</option>
            {dimensions.map((field) => (
              <option key={field.id} value={field.id}>
                {field.id}
              </option>
            ))}
            {metric?.distribution
              ? null
              : catalogue.time_groupings.map((time) => (
                  <option key={time.id} value={time.id}>
                    {time.id} of {catalogue.date_bases.find((basis) => basis.id === plan.date_basis)?.label ?? plan.date_basis}
                  </option>
                ))}
          </select>
        </label>
        <label className="chip">
          <span>Chart</span>
          <select value={plan.chart} onChange={(event) => set({ chart: event.target.value as ChartTemplateId })}>
            {catalogue.charts.map((chart) => (
              <option key={chart.id} value={chart.id} disabled={!chartFits(chart.id)}>
                {chart.label}
              </option>
            ))}
          </select>
        </label>
        <label className="chip">
          <span>Sort</span>
          <select value={plan.sort} onChange={(event) => set({ sort: event.target.value as PlanSort })} disabled={ordered}>
            {catalogue.sorts.map((sort) => (
              <option key={sort.id} value={sort.id}>
                {sort.label}
              </option>
            ))}
          </select>
        </label>
        {ordered ? null : (
          <>
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
          </>
        )}
      </div>
      {ordered ? (
        <p className="chip-note muted">
          {form === "dates"
            ? "Weeks and months are drawn in date order, every one shown; there is no bar limit or Other."
            : form === "distribution"
              ? "A distribution is drawn as one histogram of equal bins, in value order."
              : "One point per ticket; there is no bar limit or Other."}
        </p>
      ) : null}

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
          <span>Range</span>
          <select
            value={rangeChoice}
            onChange={(event) => {
              const choice = event.target.value;
              if (choice === "") set({ date_range: null });
              else if (choice === "fixed") set({ date_range: { from: null, to: asOf } });
              else set({ date_range: { relative: choice } });
            }}
          >
            <option value="">All dates</option>
            {catalogue.relative_ranges.map((range) => (
              <option key={range.id} value={range.id}>
                {range.label}
              </option>
            ))}
            <option value="fixed">Fixed dates…</option>
          </select>
        </label>
        {fixed ? (
          <>
            <label className="chip">
              <span>From</span>
              <input
                type="date"
                value={fixed.from ?? ""}
                onChange={(event) => {
                  const from = event.target.value || null;
                  set({ date_range: from || fixed.to ? { from, to: fixed.to } : null });
                }}
              />
            </label>
            <label className="chip">
              <span>To</span>
              <input
                type="date"
                value={fixed.to ?? ""}
                onChange={(event) => {
                  const to = event.target.value || null;
                  set({ date_range: fixed.from || to ? { from: fixed.from, to } : null });
                }}
              />
            </label>
          </>
        ) : null}
        <p className="chip-note muted">
          {relative
            ? "Resolved against the as-of date; the absolute range is shown with the result."
            : plan.date_range
              ? `The range applies to ${catalogue.date_bases.find((basis) => basis.id === plan.date_basis)?.label ?? plan.date_basis}.`
              : "All dates: the date basis applies once a range is set or a week or month grouping is chosen."}
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
  /** Why the displayed result is withdrawn (a new Snapshot, as-of date or review decision), or null. */
  staleReason: string | null;
  catalogue: ExploreCatalogue;
  /** The request the displayed result answers, reused for its drilldown and exports. */
  request: PlanRequest | null;
  onRerun: () => void;
  onOpenTicket: ExploreProps["onOpenTicket"];
}

function ResultPanel({ run, result, staleReason, catalogue, request, onRerun, onOpenTicket }: ResultPanelProps) {
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
      {result && request ? (
        <ResultView
          key={JSON.stringify(result.plan) + result.snapshot_fingerprint + result.as_of.date}
          result={result}
          staleReason={staleReason}
          catalogue={catalogue}
          request={request}
          onRerun={onRerun}
          onOpenTicket={onOpenTicket}
        />
      ) : null}
    </section>
  );
}

interface ResultViewProps {
  result: PlanResult;
  staleReason: string | null;
  catalogue: ExploreCatalogue;
  request: PlanRequest;
  onRerun: () => void;
  onOpenTicket: ExploreProps["onOpenTicket"];
}

/** A figure in the metric's unit, as the total line and drilldown read it. */
function amount(value: number, unit: string, statistic: string, tickets: number): string {
  return statistic === "sum" ? `${numberFormat.format(value)} ${unit} over ${numberFormat.format(tickets)} tickets` : `${numberFormat.format(value)} ${unit}`;
}

function rangeText(result: PlanResult): string | null {
  const range = result.date_range;
  if (!range) return null;
  const span = `${range.date_basis_label} from ${range.from ?? "the earliest date"} to ${range.to ?? "the latest date"}`;
  if (range.source === "relative") return `${range.label}: ${span}, resolved against the as-of date ${range.as_of}`;
  if (range.source === "overview") return `From the Overview filters: ${span}`;
  return `Fixed range: ${span}`;
}

function ResultView({ result, staleReason, catalogue, request, onRerun, onOpenTicket }: ResultViewProps) {
  const form = result.result.form;
  const dimension = result.plan.group_by[0] ?? null;
  const nouns =
    catalogue.fields.find((field) => field.id === dimension)?.nouns ??
    catalogue.time_groupings.find((time) => time.id === dimension)?.nouns ??
    (["group", "groups"] as [string, string]);
  // undefined: no drilldown open; null: every ticket in the chart; otherwise a group, bin or period id.
  const [drill, setDrill] = useState<string | null | undefined>(undefined);
  const [exportNote, setExportNote] = useState("");
  const total = result.result.total;
  const totalLine =
    total === null
      ? null
      : form === "distribution" || form === "pair"
        ? `${numberFormat.format(total)} tickets${form === "pair" ? " plotted" : ""}`
        : amount(total, result.metric.unit, result.metric.statistic, result.result.contributing_tickets);
  const drillable = (id: string) => id === "__other__" || result.result.groups.some((group) => group.id === id);
  const open = (id: string | null) => setDrill(id);
  const table = useMemo(
    () =>
      form === "pair" ? (
        <PointsTable result={result} />
      ) : (
        <ResultTable result={result} dimension={dimension} nouns={nouns} onDrill={open} />
      ),
    [result, dimension, nouns, form],
  );
  const range = rangeText(result);
  const listed = form === "distribution" || form === "pair";

  async function exportTable() {
    try {
      setExportNote(`Downloaded ${await downloadCsv("table", request)}.`);
    } catch (error: unknown) {
      setExportNote(`The table could not be downloaded: ${error instanceof Error ? error.message : String(error)}.`);
    }
  }

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
      {range ? <p className="explore-range">{range}</p> : null}
      <p className="explore-provenance muted">
        Snapshot <span className="fingerprint">{result.snapshot_fingerprint.slice(0, 12)}</span> · as of {result.as_of.date}
        {result.as_of.is_assumption ? " (assumption)" : ""} · registry {result.versions.registry} · rules {result.versions.rules} ·
        parser {result.versions.parser}
        {result.cache.status === "hit" ? " · reused from the result cache" : ""}
      </p>
      {staleReason ? (
        <div className="notice notice-error" role="alert">
          <p>{staleReason} Its numbers are withdrawn until you run the plan again.</p>
          <button type="button" className="primary-action" onClick={onRerun}>
            Rerun the plan
          </button>
        </div>
      ) : result.result.empty ? (
        <div className="empty-state" role="status">
          <p>
            <strong>Nothing to show.</strong> {result.result.empty_message}
          </p>
          <ExclusionList result={result} />
          <HowCalculatedPanel how={result.how_calculated} onInspect={() => open(null)} />
        </div>
      ) : (
        <>
          {totalLine ? <p className="chart-total num">{totalLine}</p> : null}
          {result.result.summary ? (
            <p className="muted">
              Median {numberFormat.format(result.result.summary.median ?? 0)} {result.metric.unit} · lowest{" "}
              {numberFormat.format(result.result.summary.min ?? 0)} · highest {numberFormat.format(result.result.summary.max ?? 0)}
            </p>
          ) : null}
          {listed ? <ExclusionList result={result} /> : null}
          {result.chart === null ? (
            <div className="table-only">{table}</div>
          ) : (
            <TemplateChart
              template={result.chart.template}
              spec={result.chart.spec}
              table={table}
              onSelect={form === "pair" ? undefined : (key) => (drillable(key) ? open(key) : undefined)}
            />
          )}
          {result.warnings
            // A histogram's or scatterplot's exclusions are already listed above, each with its count.
            .filter((warning) => !(listed && /left out of|not plotted because/.test(warning)))
            .map((warning) => (
              <p key={warning} className="unresolved">
                {warning}
              </p>
            ))}
          {result.notes.map((note) => (
            <p key={note} className="muted">
              {note}
            </p>
          ))}
          <div className="result-actions">
            <button type="button" className="secondary" onClick={() => open(null)}>
              Inspect source rows
            </button>
            <button type="button" className="secondary" onClick={exportTable}>
              Download the table (CSV)
            </button>
            <span className="muted" role="status">
              {exportNote}
            </span>
          </div>
          <HowCalculatedPanel how={result.how_calculated} onInspect={() => open(null)} />
        </>
      )}
      {drill !== undefined && !staleReason ? (
        <DrilldownPanel request={request} group={drill} onClose={() => setDrill(undefined)} onOpenTicket={onOpenTicket} />
      ) : null}
    </>
  );
}

/** The tickets a distribution or scatterplot leaves out, each reason with its own count: never binned or plotted at zero. */
function ExclusionList({ result }: { result: PlanResult }) {
  const excluded = result.coverage?.excluded ?? [];
  if (!excluded.length) return null;
  return (
    <div className="exclusions">
      <p className="exclusions-lead">Not in the {result.result.form === "pair" ? "scatterplot" : result.result.form === "distribution" ? "histogram" : "chart"}, each reported on its own:</p>
      <ul>
        {excluded.map((item) => (
          <li key={item.code}>
            <strong className="num">{numberFormat.format(item.tickets)}</strong> {item.tickets === 1 ? "ticket" : "tickets"}: {item.message}{" "}
            <span className="muted">(Excel rows {rowsText(item.excel_rows)})</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function rowsText(rows: number[], limit = 12): string {
  const shown = rows.slice(0, limit).join(", ");
  return rows.length > limit ? `${shown} and ${numberFormat.format(rows.length - limit)} more` : shown;
}

/** The collapsed "How this was calculated" panel: formula, exclusions, source rows and the plan itself. */
function HowCalculatedPanel({ how, onInspect }: { how: HowCalculated; onInspect: () => void }) {
  return (
    <details className="how-calculated">
      <summary>How this was calculated</summary>
      <dl>
        <dt>Formula</dt>
        <dd>{how.formula}</dd>
        <dt>Missing values</dt>
        <dd>{how.null_treatment}</dd>
        <dt>Filters</dt>
        <dd>
          {how.filters} <span className="muted">(starting filters: {how.starting_filters})</span>
        </dd>
        {how.date_range ? (
          <>
            <dt>Date range</dt>
            <dd>
              {how.date_range.label}: {how.date_range.date_basis_label} from {how.date_range.from ?? "the earliest date"} to{" "}
              {how.date_range.to ?? "the latest date"}
              {how.date_range.as_of ? `, resolved against the as-of date ${how.date_range.as_of}` : ""}
            </dd>
          </>
        ) : null}
        <dt>Exclusions</dt>
        <dd>
          {how.exclusions.length ? (
            <ul>
              {how.exclusions.map((item) => (
                <li key={item.code}>
                  {numberFormat.format(item.tickets)} {item.tickets === 1 ? "ticket" : "tickets"}{" "}
                  {item.partial ? "count only in part" : "left out"}: {item.message} (Excel rows {rowsText(item.excel_rows)})
                </li>
              ))}
            </ul>
          ) : (
            "No ticket in scope was left out."
          )}
          {how.exclusion_rules.length ? <p className="muted">Rules: {how.exclusion_rules.join("; ")}.</p> : null}
        </dd>
        <dt>Source rows</dt>
        <dd>
          {how.source_rows.tickets === 0 ? (
            `None: no ticket matches the plan. ${how.lineage}`
          ) : (
            <>
              {numberFormat.format(how.source_rows.tickets)} tickets: Excel rows {rowsText(how.source_rows.excel_rows, 30)}.{" "}
              {how.lineage}{" "}
              <button type="button" className="link-button" onClick={onInspect}>
                Inspect source rows
              </button>
            </>
          )}
        </dd>
        <dt>Chart</dt>
        <dd>{how.presentation}</dd>
        <dt>Plan</dt>
        <dd>
          <pre className="plan-json">{JSON.stringify(how.plan, null, 2)}</pre>
          {how.inherited_filters.filters ? (
            <p className="muted">Inherited beside the plan, not inside it: {how.inherited_filters.filters.description}</p>
          ) : null}
        </dd>
      </dl>
    </details>
  );
}

const PAGE = 100;

interface DrilldownPanelProps {
  request: PlanRequest;
  group: string | null;
  onClose: () => void;
  onOpenTicket: ExploreProps["onOpenTicket"];
}

/** The source tickets behind the chart or one of its marks, from the same evaluation, with CSV download. */
function DrilldownPanel({ request, group, onClose, onOpenTicket }: DrilldownPanelProps) {
  const [data, setData] = useState<DrilldownResult | null>(null);
  const [error, setError] = useState("");
  const [shown, setShown] = useState(PAGE);
  const [exportNote, setExportNote] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    setShown(PAGE);
    fetchDrilldown(request, group, controller.signal)
      .then((listing) => {
        setData(listing);
        requestAnimationFrame(() => heading.current?.focus());
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : String(failure));
      });
    return () => controller.abort();
  }, [request, group]);

  async function exportRows() {
    try {
      setExportNote(`Downloaded ${await downloadCsv("drilldown", request, group)}.`);
    } catch (failure: unknown) {
      setExportNote(`The rows could not be downloaded: ${failure instanceof Error ? failure.message : String(failure)}.`);
    }
  }

  const title = data ? `Source rows: ${data.label}` : "Source rows";
  return (
    <section className="drilldown" aria-labelledby="drilldown-heading">
      <h4 id="drilldown-heading" ref={heading} tabIndex={-1}>
        {title}
      </h4>
      {error ? (
        <p className="notice notice-error" role="alert">
          The source rows could not be loaded: {error}
        </p>
      ) : !data ? (
        <p className="status">Loading the source rows…</p>
      ) : (
        <>
          <p className="drilldown-check" role="status">
            {numberFormat.format(data.tickets)} {data.tickets === 1 ? "ticket" : "tickets"}
            {data.metric.statistic === "sum" && data.total !== null && data.value_title && !data.paired_value_title
              ? `, ${numberFormat.format(data.total)} ${data.metric.unit} in all`
              : ""}
            {data.chart_total === null
              ? "."
              : data.reproduces
                ? `, reproducing the chart's ${numberFormat.format(data.chart_total)}.`
                : `, which does not reproduce the chart's ${numberFormat.format(data.chart_total)}.`}{" "}
            <span className="muted">
              Snapshot {data.snapshot_fingerprint.slice(0, 12)} · as of {data.as_of.date} · registry {data.versions.registry}
            </span>
          </p>
          <div className="result-actions">
            <button type="button" className="secondary" onClick={exportRows} disabled={data.tickets === 0}>
              Download these rows (CSV)
            </button>
            <button type="button" className="secondary" onClick={onClose}>
              Close the source rows
            </button>
            <span className="muted" role="status">
              {exportNote}
            </span>
          </div>
          {data.rows.length ? (
            <div className="table-scroll">
              <table>
                <caption>
                  {title}: {data.filters.description}
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Ticket</th>
                    <th scope="col" className="numeric">
                      Excel row
                    </th>
                    <th scope="col">Employee</th>
                    <th scope="col">Date</th>
                    <th scope="col">Created</th>
                    <th scope="col">Status</th>
                    <th scope="col">Supervisor</th>
                    {data.value_title ? (
                      <th scope="col" className="numeric">
                        {data.value_title}
                      </th>
                    ) : null}
                    {data.paired_value_title ? (
                      <th scope="col" className="numeric">
                        {data.paired_value_title}
                      </th>
                    ) : null}
                    <th scope="col">Description of Job Work</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.slice(0, shown).map((row) => (
                    <tr key={row.excel_row}>
                      <th scope="row">
                        <button
                          type="button"
                          className="link-button"
                          onClick={(event) => onOpenTicket(row, data.snapshot_fingerprint, event.currentTarget)}
                        >
                          {row.ticket_number ?? `Row ${row.excel_row}`}
                        </button>
                      </th>
                      <td className="numeric num">{row.excel_row}</td>
                      <td>{row.employee ?? "—"}</td>
                      <td className="num">{row.date ?? "—"}</td>
                      <td className="num">{row.created ? row.created.replace("T", " ").slice(0, 16) : "—"}</td>
                      <td>{row.status ?? "Unreadable"}</td>
                      <td>{row.supervisor ?? "—"}</td>
                      {data.value_title ? <td className="numeric num">{row.value === null ? "—" : numberFormat.format(row.value)}</td> : null}
                      {data.paired_value_title ? (
                        <td className="numeric num">
                          {row.paired_value === null || row.paired_value === undefined ? "—" : numberFormat.format(row.paired_value)}
                        </td>
                      ) : null}
                      <td className="description-cell">{row.description === null ? "—" : String(row.description)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="status">No tickets: nothing is listed.</p>
          )}
          {data.rows.length > shown ? (
            <p>
              Showing {numberFormat.format(shown)} of {numberFormat.format(data.rows.length)}.{" "}
              <button type="button" className="secondary" onClick={() => setShown((value) => value + PAGE)}>
                Show {Math.min(PAGE, data.rows.length - shown)} more
              </button>
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}

interface ResultTableProps {
  result: PlanResult;
  dimension: string | null;
  nouns: [string, string];
  onDrill: (id: string) => void;
}

function ResultTable({ result, dimension, nouns, onDrill }: ResultTableProps) {
  const { groups, other, value_title: valueTitle } = result.result;
  // A count's value is its tickets; a sum also says how many tickets it adds up.
  const counted = result.metric.statistic === "sum";
  const form = result.result.form;
  const heading =
    form === "distribution"
      ? `${result.metric.label} (${result.metric.unit})`
      : form === "dates"
        ? `${dimension} of ${result.filters.date_basis.label}`
        : (dimension ?? "Plan");
  const noun = form === "distribution" ? "range" : dimension ? nouns[0] : "total";
  const where = (group: PlanResult["result"]["groups"][number]) =>
    form === "dates" || form === "distribution"
      ? group.shown
        ? "Drawn"
        : "Listed apart, not drawn"
      : group.shown
        ? "Own bar"
        : group.in_other
          ? "In Other"
          : "Not drawn";
  return (
    <div className="table-scroll">
      <table>
        <caption>
          {result.title}, {result.filters.description}: every {noun}
          {form === "categories" ? ", including any combined as Other" : ""}
        </caption>
        <thead>
          <tr>
            <th scope="col">{heading}</th>
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
              <th scope="row">
                <button
                  type="button"
                  className="link-button"
                  aria-label={`Show the ${numberFormat.format(group.contributing_tickets)} source rows for ${group.label}`}
                  onClick={() => onDrill(group.id)}
                >
                  {group.label}
                </button>
              </th>
              <td className="numeric num">{numberFormat.format(group.value)}</td>
              {counted ? <td className="numeric num">{numberFormat.format(group.contributing_tickets)}</td> : null}
              <td>{where(group)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          {other ? (
            <tr>
              <th scope="row">
                <button
                  type="button"
                  className="link-button"
                  aria-label={`Show the ${numberFormat.format(other.contributing_tickets)} source rows for ${other.label}`}
                  onClick={() => onDrill(other.id)}
                >
                  {other.label}
                </button>
              </th>
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

/** A scatterplot's table alternative: every plotted ticket with its two values. */
function PointsTable({ result }: { result: PlanResult }) {
  const points = result.result.points ?? [];
  const paired = result.paired_metric;
  return (
    <div className="table-scroll table-tall">
      <table>
        <caption>
          {result.title}, {result.filters.description}: all {numberFormat.format(points.length)} plotted tickets
        </caption>
        <thead>
          <tr>
            <th scope="col" className="numeric">
              Excel row
            </th>
            <th scope="col" className="numeric">
              {result.metric.label} ({result.metric.unit})
            </th>
            <th scope="col" className="numeric">
              {paired ? `${paired.label} (${paired.unit})` : "Paired value"}
            </th>
          </tr>
        </thead>
        <tbody>
          {points.map((point) => (
            <tr key={point.excel_row}>
              <th scope="row" className="numeric num">
                {point.excel_row}
              </th>
              <td className="numeric num">{numberFormat.format(point.x)}</td>
              <td className="numeric num">{numberFormat.format(point.y)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
