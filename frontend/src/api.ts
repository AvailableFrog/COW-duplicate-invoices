// Types mirror the JSON the Python API returns. Every numeric response carries
// the Snapshot fingerprint, the registry, rule and parser versions, and the
// as-of date in effect.

export interface ImportIssue {
  excel_row: number;
  /** Null for an issue about the whole row, such as a blank row. */
  field: string | null;
  code: string;
  message: string;
}

export interface DisabledFeature {
  column: string;
  kind: "metric" | "grouping" | "check" | "display";
  feature: string;
  reason: string;
}

export interface SnapshotHeader {
  fingerprint: string;
  fingerprint_algorithm: string;
  workbook_name: string;
  sheet: string;
  row_count: number;
  field_count: number;
  fields: string[];
  imported_at: string;
  import_issue_count: number;
  import_issues: ImportIssue[];
  missing_optional_columns: string[];
  disabled_features: DisabledFeature[];
}

export interface AsOf {
  date: string;
  is_assumption: boolean;
  is_default: boolean;
  default: string;
  note: string;
}

export interface Versions {
  app: string;
  registry: string;
  rules: string;
  parser: string;
}

/** Carried by every response with numbers: the Snapshot, as-of date and versions they were computed under. */
export interface Provenance {
  snapshot_fingerprint: string;
  as_of: AsOf;
  versions: Versions;
}

export interface HeaderResponse extends Provenance {
  snapshot: SnapshotHeader;
}

export type DateBasis = "Created" | "Date" | "Date Approved";
export type ApprovalStatus = "Approved" | "Pending" | "Rejected";

/** The global filter bar's state; an empty list or null range means "all". */
export interface FilterState {
  dateBasis: DateBasis;
  dateFrom: string | null;
  dateTo: string | null;
  job: number | null;
  status: ApprovalStatus | null;
}

export const NO_FILTERS: FilterState = { dateBasis: "Created", dateFrom: null, dateTo: null, job: null, status: null };

export interface FilterPayload {
  date_basis: { id: DateBasis; label: string };
  date_range: { from: string | null; to: string | null } | null;
  jobs: number[];
  statuses: ApprovalStatus[];
  active: boolean;
  description: string;
}

export interface FilterOptions extends Provenance {
  date_bases: { id: DateBasis; label: string; available: boolean; earliest: string | null; latest: string | null }[];
  statuses: { id: ApprovalStatus; tickets: number }[];
  jobs: { job_number: number; job_name: string | null; tickets: number }[];
}

export interface Percentage {
  numerator: number;
  denominator: number;
  denominator_metric: string;
  ratio: number | null;
}

export interface Tile {
  metric_id: string;
  label: string;
  value: number | null;
  /** For a tile counting possible duplicates, the Tickets they hold; null for Ticket counts. */
  tickets: number | null;
  unit: string;
  definition: string;
  percentage: Percentage | null;
  warnings: string[];
}

export interface TilesResponse extends Provenance {
  tiles: Tile[];
  note: string;
  grain: string;
  filters: FilterPayload;
}

export interface Member {
  excel_row: number;
  ticket_number: string | null;
  employee: string | null;
  date: string | null;
  job_number: number | null;
  status: ApprovalStatus | null;
  keyed: boolean | null;
  flagged_duplicate: boolean;
  created: string | null;
  in_filter: boolean;
}

export type OutcomeId = "not_reviewed" | "confirmed_duplicate" | "not_a_duplicate" | "replacement_ticket" | "needs_follow_up";

export interface OutcomeLabel {
  id: OutcomeId;
  label: string;
}

export interface Candidate {
  excel_rows: [number, number];
  rule_id: string;
  fields_compared: string[];
  evidence_strength: string;
  reason: string;
  /** The Review Outcome saved on this Candidate's Ticket pair; Not reviewed when none. Display only, never a rank input. */
  outcome: OutcomeLabel;
}

export interface PriorityTier {
  rank: number;
  id: string;
  label: string;
}

export interface PossibleDuplicate {
  rank: number;
  /** Derived from the sorted member ticket numbers; a display name, never a storage key. */
  display_id: string;
  tier: PriorityTier;
  exact_repeat_not_flagged: boolean;
  rule_ids: string[];
  pattern_labels: string[];
  summary: string;
  members: Member[];
  candidates: Candidate[];
}

export interface Rule {
  id: string;
  label: string;
  pattern: string;
  evidence_strength: string;
  fields_compared: string[];
  reason: string;
}

export interface ReviewPrioritiesResponse extends Provenance {
  possible_duplicates: PossibleDuplicate[];
  tiers: PriorityTier[];
  rules: Rule[];
  note: string;
  filters: FilterPayload;
}

/** One source cell exactly as imported: a blank has raw type "blank" and a null value; 0 and false stay typed. */
export interface SourceCell {
  raw_type: string;
  value: string | number | boolean | null;
  number_format: string | null;
}

export interface TimeInterval {
  start: string;
  end: string;
}

export interface TimePeriod {
  text: string;
  confidence: "confident" | "ambiguous";
  interval: TimeInterval | null;
  plausible_reading: (TimeInterval & { assumed: true }) | null;
  flags: string[];
  notes: string[];
}

export interface TimeParse {
  raw_time: { raw_type: string; value: string | number | boolean | null };
  parser_version: string;
  status: string;
  periods: TimePeriod[];
  confident_union: TimeInterval[];
  notes: string[];
}

export interface TimeComparison {
  result: "overlap" | "separate" | "ambiguous" | "undetermined";
  basis: string | null;
  assumed: boolean;
  intersection: TimeInterval[];
  overlap_minutes: number;
  explanation: string;
}

export interface EvidenceCandidate extends Candidate {
  rule_label: string;
  time_comparison: TimeComparison;
}

export interface EvidenceMember extends Member {
  provenance: { snapshot_fingerprint: string; sheet: string; excel_row: number; dataframe_index: number };
  issues: ImportIssue[];
  time_parse: TimeParse;
}

export interface StatusBreakdown {
  status: ApprovalStatus | null;
  keyed: boolean | null;
  flagged_duplicate: boolean;
  label: string;
  tickets: number;
}

export interface SourceFieldRow {
  field: string;
  position: number;
  differs: boolean;
  /** One per member, in member order. */
  cells: (SourceCell & { excel_row: number })[];
}

export interface Annotation {
  letter: string;
  title: string;
  pattern: { number: number; title: string };
  summary: string;
  /** The requester's condensed review note; null where the evidence report gives none. */
  review_note: string | null;
  /** True where the note was reworded so no banned phrase reaches a screen; source_section holds the original. */
  review_note_reworded: boolean;
  /** Where the example sits in the evidence report. */
  source_section: string;
  questions_for_oliver: string[];
  what_the_answer_changes: string;
  tickets: { ticket_number: string; excel_row: number | null; report_excel_row: number; in_possible_duplicate: boolean }[];
}

export interface OutcomeValue extends OutcomeLabel {
  definition: string;
}

/** A Ticket pair's Review Outcome; `saved` is false (and reviewer null) until someone saves one. */
export interface PairOutcome {
  excel_rows: [number, number];
  ticket_numbers: [string | null, string | null];
  outcome: OutcomeLabel;
  note: string;
  reference: string;
  reviewer: string | null;
  recorded_at: string | null;
  saved: boolean;
}

/** One replaced Ticket and one kept (retained) Ticket; a replaced Ticket may have several. */
export interface ReplacementLink {
  replaced_row: number;
  retained_row: number;
  replaced_ticket_number: string | null;
  retained_ticket_number: string | null;
  reviewer: string;
  recorded_at: string;
  rationale: string;
}

export interface OutcomeHistoryValue {
  outcome: OutcomeLabel;
  note: string;
  reference: string;
}

export interface LinkHistoryValue {
  replaced_row: number;
  retained_row: number;
  replaced_ticket_number: string | null;
  retained_ticket_number: string | null;
}

export type HistoryEntry = {
  entry: number;
  /** For an outcome the pair, lower row first; for a link the replaced row, then the kept row. */
  excel_rows: [number, number];
  ticket_numbers: [string | null, string | null];
  reviewer: string;
  recorded_at: string;
  rationale: string;
} & (
  | { kind: "outcome"; previous: OutcomeHistoryValue | null; new: OutcomeHistoryValue | null }
  | { kind: "link"; previous: LinkHistoryValue | null; new: LinkHistoryValue | null }
);

export interface PossibleDuplicateReview {
  outcome_values: OutcomeValue[];
  pairs: (PairOutcome & { rule_ids: string[] })[];
  links: ReplacementLink[];
  /** Newest first. */
  history: HistoryEntry[];
}

export interface EvidenceResponse extends Provenance {
  display_id: string;
  tier: PriorityTier;
  exact_repeat_not_flagged: boolean;
  rule_ids: string[];
  pattern_labels: string[];
  reason: string;
  candidates: EvidenceCandidate[];
  status_breakdown: StatusBreakdown[];
  members: EvidenceMember[];
  timeline: { fields: string[]; entries: { excel_row: number; ticket_number: string | null; cells: (SourceCell | null)[] }[] };
  fields: SourceFieldRow[];
  differing_fields: string[];
  annotations: Annotation[];
  review: PossibleDuplicateReview;
}

async function failure(response: Response): Promise<Error> {
  let detail = `${response.status} ${response.statusText}`;
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") detail = body.detail;
    else if (body.detail && typeof body.detail === "object" && "message" in body.detail) {
      detail = String((body.detail as { message: unknown }).message);
    }
  } catch {
    // keep the status line
  }
  return new Error(detail);
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

export function filterQuery(filters: FilterState): string {
  const params = new URLSearchParams({ date_basis: filters.dateBasis });
  if (filters.dateFrom) params.set("date_from", filters.dateFrom);
  if (filters.dateTo) params.set("date_to", filters.dateTo);
  if (filters.job !== null) params.set("job", String(filters.job));
  if (filters.status !== null) params.set("status", filters.status);
  return params.toString();
}

export function fetchHeader(signal?: AbortSignal): Promise<HeaderResponse> {
  return getJson<HeaderResponse>("/api/snapshot", signal);
}

export function fetchFilterOptions(signal?: AbortSignal): Promise<FilterOptions> {
  return getJson<FilterOptions>("/api/filters", signal);
}

export function fetchTiles(filters: FilterState, signal?: AbortSignal): Promise<TilesResponse> {
  return getJson<TilesResponse>(`/api/overview/tiles?${filterQuery(filters)}`, signal);
}

export function fetchReviewPriorities(filters: FilterState, signal?: AbortSignal): Promise<ReviewPrioritiesResponse> {
  return getJson<ReviewPrioritiesResponse>(`/api/review-priorities?${filterQuery(filters)}`, signal);
}

/** The evidence for the possible duplicate holding a Ticket, addressed by that Ticket's Snapshot and Excel row. */
export function fetchEvidence(
  fingerprint: string,
  excelRow: number,
  filters: FilterState,
  signal?: AbortSignal,
): Promise<EvidenceResponse> {
  return getJson<EvidenceResponse>(
    `/api/snapshots/${encodeURIComponent(fingerprint)}/tickets/${excelRow}/possible-duplicate?${filterQuery(filters)}`,
    signal,
  );
}

/** Change the analytical as-of date; later responses are computed against it. */
export async function changeAsOf(date: string): Promise<Provenance> {
  const response = await fetch("/api/as-of", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date }),
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as Provenance;
}

export interface ReimportResponse extends HeaderResponse {
  imported: boolean;
}

/** Re-read the workbook at the launch path; identical content keeps the same Snapshot. */
export async function reimportWorkbook(): Promise<ReimportResponse> {
  const response = await fetch("/api/snapshot/reimport", { method: "POST" });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as ReimportResponse;
}

async function sendJson<T>(method: "PUT" | "DELETE", path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

export interface OutcomeChange {
  outcome: OutcomeId;
  note: string;
  reference: string;
  reviewer: string;
  rationale: string;
}

/** Save a Review Outcome on a Ticket pair; either row order names the same pair. */
export function saveOutcome(
  fingerprint: string,
  pair: [number, number],
  change: OutcomeChange,
): Promise<PairOutcome & { changed: boolean; history: HistoryEntry[] }> {
  return sendJson("PUT", `/api/snapshots/${encodeURIComponent(fingerprint)}/pairs/${pair[0]}/${pair[1]}/outcome`, change);
}

function linkPath(fingerprint: string, replacedRow: number, retainedRow: number): string {
  return `/api/snapshots/${encodeURIComponent(fingerprint)}/replacement-links/${replacedRow}/${retainedRow}`;
}

/** Record that one Ticket was replaced and another kept. */
export function linkReplacement(
  fingerprint: string,
  replacedRow: number,
  retainedRow: number,
  change: { reviewer: string; rationale: string },
): Promise<ReplacementLink & { changed: boolean }> {
  return sendJson("PUT", linkPath(fingerprint, replacedRow, retainedRow), change);
}

/** Remove a kept/replaced link; the history keeps what it was. */
export function unlinkReplacement(
  fingerprint: string,
  replacedRow: number,
  retainedRow: number,
  change: { reviewer: string; rationale: string },
): Promise<ReplacementLink & { removed: boolean }> {
  return sendJson("DELETE", linkPath(fingerprint, replacedRow, retainedRow), change);
}
