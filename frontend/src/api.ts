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
  /** The normalized label the rules compare; two labels stay two even under a confirmed Alias. */
  employee_label: string | null;
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
  /** The PRD pattern this match illustrates, usually its rule's. */
  pattern: string;
  /** The Review Outcome saved on this Candidate's Ticket pair; Not reviewed when none. Settling a flagged duplicate's counterpart pair moves its tier; nothing else does. */
  outcome: OutcomeLabel;
}

export interface PriorityTier {
  rank: number;
  id: string;
  label: string;
}

export type PatternId =
  | "same_claim_twice"
  | "same_claim_as_different_text"
  | "correction_or_resubmission"
  | "equal_duration_separate_periods"
  | "repeated_payment_component";

export type SourceStateId =
  | "approved_keyed"
  | "approved_not_keyed"
  | "pending"
  | "rejected"
  | "flagged_duplicate"
  | "unreadable";

/** A PRD section 5 pattern a Candidate can carry. */
export interface PatternRef {
  id: PatternId;
  number: number;
  label: string;
}

/** A matrix column: one recorded source state; every Ticket has exactly one. */
export interface SourceStateDefinition {
  id: SourceStateId;
  label: string;
  definition: string;
}

/** The pattern filter on Review priorities; empty lists mean any pattern and any state. */
export interface PatternFilterState {
  patterns: PatternId[];
  sourceStates: SourceStateId[];
}

export const NO_PATTERN_FILTER: PatternFilterState = { patterns: [], sourceStates: [] };

/** A member of a listed possible duplicate: its source state, and whether it is counted under the pattern filter. */
export interface PriorityMember extends Member {
  source_state: SourceStateId;
  /** Inside the global filters, in a selected source state and linked by a selected pattern. */
  in_selection: boolean;
}

export interface PossibleDuplicate {
  rank: number;
  /** Derived from the sorted member ticket numbers; a display name, never a storage key. */
  display_id: string;
  tier: PriorityTier;
  exact_repeat_not_flagged: boolean;
  rule_ids: string[];
  pattern_labels: string[];
  pattern_ids: PatternId[];
  /** How many members are in each source state, inside the filters or not. */
  source_states: { id: SourceStateId; label: string; tickets: number }[];
  summary: string;
  members: PriorityMember[];
  candidates: Candidate[];
}

/** Distinct possible duplicates and distinct Tickets; a union, never a sum of overlapping counts. */
export interface DistinctTotals {
  possible_duplicates: number;
  tickets: number;
}

export interface PatternCount extends PatternRef, DistinctTotals {
  selected: boolean;
}

export interface PatternFilterPayload {
  patterns: PatternId[];
  source_states: SourceStateId[];
  active: boolean;
  description: string;
  /** Each pattern on its own, under the global filters and the selected source states. */
  counts: PatternCount[];
  /** The union over the selected patterns: what the list holds. */
  totals: DistinctTotals;
  note: string;
}

export interface MatrixRow extends DistinctTotals {
  cells: { source_state: SourceStateId; tickets: number }[];
}

export interface PatternMatrix {
  caption: string;
  note: string;
  grain: string;
  source_states: SourceStateDefinition[];
  rows: (MatrixRow & { pattern: PatternRef })[];
  /** Each Ticket once, whatever patterns link it. */
  any_pattern: MatrixRow;
}

export interface Rule {
  id: string;
  label: string;
  pattern: string;
  evidence_strength: string;
  fields_compared: string[];
  reason: string;
  /** Whether a confirmed Alias widens this rule's employee key. */
  accepts_alias: boolean;
}

export interface ReviewPrioritiesResponse extends Provenance {
  possible_duplicates: PossibleDuplicate[];
  pattern_filter: PatternFilterPayload;
  pattern_matrix: PatternMatrix;
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

export type AliasDecisionId = "proposed" | "confirmed" | "rejected";

export interface AliasDecisionLabel {
  id: AliasDecisionId;
  label: string;
}

export interface AliasHistoryValue {
  labels: [string, string];
  decision: AliasDecisionLabel;
}

export type HistoryEntry = {
  entry: number;
  /**
   * For an outcome the pair, lower row first; for a link the replaced row, then the kept row;
   * for an Alias decision the rows of the tickets proposing it.
   */
  excel_rows: number[];
  ticket_numbers: (string | null)[];
  reviewer: string;
  recorded_at: string;
  rationale: string;
} & (
  | { kind: "outcome"; previous: OutcomeHistoryValue | null; new: OutcomeHistoryValue | null }
  | { kind: "link"; previous: LinkHistoryValue | null; new: LinkHistoryValue | null }
  | { kind: "alias"; employee_labels: [string, string]; previous: AliasHistoryValue | null; new: AliasHistoryValue | null }
);

/** A proposed Alias: two employee labels the Name-space variant found on the same claim, with the reviewer's decision. */
export interface AliasProposal {
  /** The normalized labels, sorted: the key the decision is stored under. */
  labels: [string, string];
  /** The names as written on the tickets. */
  names: string[];
  /** The Ticket pairs proposing it, Excel rows lower first. */
  proposed_by: [number, number][];
  decision: AliasDecisionLabel;
  reviewer: string | null;
  recorded_at: string | null;
  rationale: string;
  saved: boolean;
  history: HistoryEntry[];
}

export interface PossibleDuplicateReview {
  outcome_values: OutcomeValue[];
  alias_decision_values: (AliasDecisionLabel & { definition: string })[];
  /** Aliases about two of the members' labels: proposed here, or widening a rule here once confirmed. */
  aliases: AliasProposal[];
  pairs: (PairOutcome & { rule_ids: string[] })[];
  links: ReplacementLink[];
  /** Newest first. */
  history: HistoryEntry[];
}

/** The evidence shown for any set of Tickets, in the drawer for a possible duplicate or a compared pair. */
export interface ShownEvidence {
  members: EvidenceMember[];
  timeline: { fields: string[]; entries: { excel_row: number; ticket_number: string | null; cells: (SourceCell | null)[] }[] };
  fields: SourceFieldRow[];
  differing_fields: string[];
  annotations: Annotation[];
}

export interface EvidenceResponse extends Provenance, ShownEvidence {
  display_id: string;
  tier: PriorityTier;
  exact_repeat_not_flagged: boolean;
  rule_ids: string[];
  pattern_labels: string[];
  reason: string;
  candidates: EvidenceCandidate[];
  status_breakdown: StatusBreakdown[];
  review: PossibleDuplicateReview;
}

/** One rule's answer for a Ticket pair: whether it matched, and why or why not. */
export interface RuleVerdict {
  rule_id: string;
  rule_label: string;
  matched: boolean;
  evidence_strength: string;
  fields_compared: string[];
  reason: string;
}

export interface PairMember extends EvidenceMember {
  /** The display name of the possible duplicate this Ticket is in; null when it is in none. */
  possible_duplicate: string | null;
}

/** Why two Tickets are or are not linked, with or without a Candidate. */
export interface PairExplanation extends Provenance, ShownEvidence {
  excel_rows: [number, number];
  /** Inside the search space: the same Date, and the same label, a spacing variant or a confirmed Alias. */
  same_employee_and_date: boolean;
  employee_relation: "same_label" | "confirmed_alias" | "spacing_differs" | "different" | "unusable";
  linked: boolean;
  rules: RuleVerdict[];
  summary: string;
  time_comparison: TimeComparison;
  /** The possible duplicate holding both Tickets, if one does. */
  possible_duplicate: string | null;
  members: PairMember[];
}

/** One Ticket's evidence on its own, such as a flagged duplicate no rule links. */
export interface TicketEvidence extends Provenance, ShownEvidence {
  excel_row: number;
  /** The display name of the possible duplicate this Ticket is in; null when it is in none. */
  possible_duplicate: string | null;
  members: PairMember[];
}

/** A Ticket the Flagged-duplicate counterpart rule links to a flagged duplicate; never chosen as the original. */
export interface Counterpart extends Member {
  excel_rows: [number, number];
  /** False for an uncertain counterpart, found only through the same unresolved Time text and description. */
  certain: boolean;
  reason: string;
  /** Whether a reviewer settled this pair: Confirmed duplicate, Replacement ticket or a kept/replaced link. */
  settles: boolean;
  outcome: OutcomeLabel;
}

export type CounterpartStatusId = "counterpart_found" | "unresolved";

export interface FlaggedDuplicate extends Member {
  counterpart_status: { id: CounterpartStatusId; label: string };
  counterparts: Counterpart[];
  /** A reviewer settled one of its counterpart pairs, so it no longer holds its possible duplicate in tier 3. */
  settled_by_review: boolean;
  possible_duplicate: { display_id: string; tier: PriorityTier } | null;
}

export interface FlaggedDuplicatesResponse extends Provenance {
  flagged_duplicates: FlaggedDuplicate[];
  counts: { flagged_duplicates: number; counterpart_found: number; unresolved: number };
  counterpart_statuses: { id: CounterpartStatusId; label: string; definition: string }[];
  metric_id: string;
  note: string;
  filters: FilterPayload;
}

/** A range of a distribution metric's values, both ends inclusive; `max` null is open-ended. */
export interface MetricBucket {
  id: string;
  label: string;
  min: number;
  max: number | null;
}

export interface BucketCount extends MetricBucket {
  tickets: number;
}

export interface CoverageItem {
  code: string;
  message: string;
  tickets: number;
  excel_rows: number[];
}

export interface DistributionSummary {
  count: number;
  median: number | null;
  min: number | null;
  max: number | null;
  mean: number | null;
}

/** One Processing queue chart: a registry age metric counted by its buckets. */
export interface QueueChart {
  metric_id: string;
  title: string;
  /** The population in a few words, such as "Pending". */
  population: string;
  label: string;
  definition: string;
  unit: string;
  caption: string;
  measured_on: string;
  chart: "bar_horizontal";
  availability: { status: "available" | "disabled"; reason: string | null };
  total: number;
  summary: DistributionSummary | null;
  buckets: BucketCount[];
  coverage: { contributing_tickets: number; excluded: CoverageItem[]; partial: CoverageItem[] } | null;
  warnings: string[];
}

export interface ProcessingQueueResponse extends Provenance {
  charts: QueueChart[];
  caption: string;
  note: string;
  grain: string;
  filters: FilterPayload;
}

/** A Ticket one bucket counts, with its value in the metric's unit (days of age since submission here). */
export interface BucketTicket {
  excel_row: number;
  ticket_number: string | null;
  employee: string | null;
  date: string | null;
  created: string | null;
  status: ApprovalStatus | null;
  keyed: boolean | null;
  value: number;
}

export interface BucketTicketsResponse extends Provenance {
  metric: { id: string; label: string; definition: string; unit: string };
  bucket: MetricBucket;
  grain: string;
  filters: FilterPayload;
  tickets: number;
  rows: BucketTicket[];
}

export interface ValueCoverageItem extends CoverageItem {
  quantity?: number | null;
  quantity_unit?: string | null;
}

/** One exact repeat, not flagged, behind the hypothetical figure: n tickets and the n − 1 extra claims valued. */
export interface ExtraClaimGroup {
  excel_rows: number[];
  ticket_numbers: (string | null)[];
  employee: string | null;
  tickets: number;
  extra_claims: number;
  ticket_values: number[];
  value: number;
  /** The evidence report's example letters naming its tickets, such as "C". */
  examples: string[];
}

export type ValueScenario = "recorded" | "flagged" | "hypothetical" | "analyst_reviewed";

/** One BBD figure of the value-context panel: a registry metric with its formula, interpretation and completeness. */
export interface ValueFigure {
  id: string;
  metric_id: string;
  label: string;
  scenario: ValueScenario;
  value: number | null;
  currency: "BBD";
  formula: string;
  interpretation: string;
  completeness: string;
  definition: string;
  grain: string;
  tickets: number;
  availability: { status: "available" | "disabled"; reason: string | null };
  coverage: { contributing_tickets: number; excluded: ValueCoverageItem[]; partial: ValueCoverageItem[] } | null;
  warnings: string[];
  possible_duplicates?: ExtraClaimGroup[];
}

export interface ReviewedAlternative extends ValueFigure {
  replaced_tickets: number[];
  replaced_in_filter: number[];
  left_out_value: number | null;
}

export interface ValueContextResponse extends Provenance {
  title: string;
  currency: "BBD";
  note: string;
  figures: ValueFigure[];
  unpriced_labour: {
    tickets: number;
    hours: number;
    statuses: { status: ApprovalStatus | null; tickets: number }[];
    excel_rows: number[];
    /** In words, such as "881 hours across 122 Pending tickets that lack a usable Rate or hour value". */
    summary: string;
  };
  /** Present only when a reviewer's kept/replaced link marks a ticket replaced. */
  reviewed_alternative: ReviewedAlternative | null;
  filters: FilterPayload;
}

/** A refused or failed request, with its HTTP status. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function failure(response: Response): Promise<ApiError> {
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
  return new ApiError(detail, response.status);
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

export function fetchReviewPriorities(
  filters: FilterState,
  patternFilter: PatternFilterState,
  signal?: AbortSignal,
): Promise<ReviewPrioritiesResponse> {
  const params = new URLSearchParams(filterQuery(filters));
  for (const pattern of patternFilter.patterns) params.append("pattern", pattern);
  for (const state of patternFilter.sourceStates) params.append("source_state", state);
  return getJson<ReviewPrioritiesResponse>(`/api/review-priorities?${params.toString()}`, signal);
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

/** Every flagged duplicate inside the filters, with counterpart found or unresolved. */
export function fetchFlaggedDuplicates(filters: FilterState, signal?: AbortSignal): Promise<FlaggedDuplicatesResponse> {
  return getJson<FlaggedDuplicatesResponse>(`/api/flagged-duplicates?${filterQuery(filters)}`, signal);
}

/** One Ticket's evidence on its own, addressed by its Snapshot and Excel row. */
export function fetchTicketEvidence(
  fingerprint: string,
  excelRow: number,
  filters: FilterState,
  signal?: AbortSignal,
): Promise<TicketEvidence> {
  return getJson<TicketEvidence>(
    `/api/snapshots/${encodeURIComponent(fingerprint)}/tickets/${excelRow}/evidence?${filterQuery(filters)}`,
    signal,
  );
}

/** Why two Tickets are or are not linked: every rule's verdict and how their work periods compare. */
export function fetchPairExplanation(
  fingerprint: string,
  rows: [number, number],
  filters: FilterState,
  signal?: AbortSignal,
): Promise<PairExplanation> {
  return getJson<PairExplanation>(
    `/api/snapshots/${encodeURIComponent(fingerprint)}/pairs/${rows[0]}/${rows[1]}?${filterQuery(filters)}`,
    signal,
  );
}

/** The Processing queue's two age-since-submission charts under the filters. */
export function fetchProcessingQueue(filters: FilterState, signal?: AbortSignal): Promise<ProcessingQueueResponse> {
  return getJson<ProcessingQueueResponse>(`/api/overview/processing-queue?${filterQuery(filters)}`, signal);
}

/** The value-context panel's BBD figures under the filters, with any analyst-reviewed alternative. */
export function fetchValueContext(filters: FilterState, signal?: AbortSignal): Promise<ValueContextResponse> {
  return getJson<ValueContextResponse>(`/api/overview/value-context?${filterQuery(filters)}`, signal);
}

/** The Tickets one bucket of a registry metric counts, under the same filters as its chart. */
export function fetchBucketTickets(
  metricId: string,
  bucketId: string,
  filters: FilterState,
  signal?: AbortSignal,
): Promise<BucketTicketsResponse> {
  return getJson<BucketTicketsResponse>(
    `/api/metrics/${encodeURIComponent(metricId)}/buckets/${encodeURIComponent(bucketId)}?${filterQuery(filters)}`,
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

export interface AliasChange {
  labels: [string, string];
  decision: Exclude<AliasDecisionId, "proposed">;
  reviewer: string;
  rationale: string;
}

/** A Candidate a rule run added or removed, with its rule's name. */
export type RerunCandidate = Omit<Candidate, "outcome"> & { rule_label: string };

/** What a rule run changed after an Alias decision. */
export interface RuleRerun {
  added: RerunCandidate[];
  removed: RerunCandidate[];
}

/** Confirm or reject a proposed Alias; a change runs the matching rules again over the Snapshot. */
export function saveAlias(
  fingerprint: string,
  change: AliasChange,
): Promise<AliasProposal & { changed: boolean; rules_ran: boolean; rerun: RuleRerun }> {
  return sendJson("PUT", `/api/snapshots/${encodeURIComponent(fingerprint)}/aliases`, change);
}
