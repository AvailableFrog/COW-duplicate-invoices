import type { ApprovalStatus, DateBasis, FilterOptions, FilterPayload, FilterState } from "./api";
import { NO_FILTERS } from "./api";

const numberFormat = new Intl.NumberFormat("en-GB");

interface FilterBarProps {
  options: FilterOptions | null;
  filters: FilterState;
  onChange: (filters: FilterState) => void;
}

/** The global filter bar: date basis and range, job and status, with Clear. */
export function FilterBar({ options, filters, onChange }: FilterBarProps) {
  const set = (patch: Partial<FilterState>) => onChange({ ...filters, ...patch });
  const basis = options?.date_bases.find((item) => item.id === filters.dateBasis);
  return (
    <form className="filter-bar" aria-label="Filters" onSubmit={(event) => event.preventDefault()}>
      <label>
        <span>Date basis</span>
        <select value={filters.dateBasis} onChange={(event) => set({ dateBasis: event.target.value as DateBasis })}>
          {(options?.date_bases ?? []).map((item) => (
            <option key={item.id} value={item.id} disabled={!item.available}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>From</span>
        <input
          type="date"
          value={filters.dateFrom ?? ""}
          min={basis?.earliest ?? undefined}
          max={basis?.latest ?? undefined}
          onChange={(event) => set({ dateFrom: event.target.value || null })}
        />
      </label>
      <label>
        <span>To</span>
        <input
          type="date"
          value={filters.dateTo ?? ""}
          min={basis?.earliest ?? undefined}
          max={basis?.latest ?? undefined}
          onChange={(event) => set({ dateTo: event.target.value || null })}
        />
      </label>
      <label>
        <span>Job</span>
        <select
          value={filters.job === null ? "" : String(filters.job)}
          onChange={(event) => set({ job: event.target.value === "" ? null : Number(event.target.value) })}
        >
          <option value="">All jobs</option>
          {(options?.jobs ?? []).map((job) => (
            <option key={job.job_number} value={job.job_number}>
              {job.job_number}
              {job.job_name ? ` ${job.job_name}` : ""} ({numberFormat.format(job.tickets)})
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Status</span>
        <select
          value={filters.status ?? ""}
          onChange={(event) => set({ status: (event.target.value || null) as ApprovalStatus | null })}
        >
          <option value="">All statuses</option>
          {(options?.statuses ?? []).map((status) => (
            <option key={status.id} value={status.id}>
              {status.id} ({numberFormat.format(status.tickets)})
            </option>
          ))}
        </select>
      </label>
      <button type="button" className="secondary" onClick={() => onChange(NO_FILTERS)}>
        Clear
      </button>
    </form>
  );
}

/** The active filter state and aggregation grain, shown on every view. */
export function ActiveFilters({ filters, grain }: { filters: FilterPayload | null; grain: string }) {
  return (
    <p className="active-filters" role="status">
      <span className="muted">Showing </span>
      {filters ? filters.description : "…"}
      <span className="muted"> · Grain </span>
      {grain}
      {filters && !filters.date_range ? (
        <span className="muted"> · date basis {filters.date_basis.label} (applies when a range is set)</span>
      ) : null}
    </p>
  );
}
