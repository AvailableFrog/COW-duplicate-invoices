// Types mirror the JSON the Python API returns. Every numeric response carries
// the Snapshot fingerprint and the as-of date in effect.

export interface ImportIssue {
  excel_row: number;
  field: string;
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
  note: string;
}

export interface HeaderResponse {
  snapshot: SnapshotHeader;
  as_of: AsOf;
  versions: { app: string };
}

export async function fetchHeader(signal?: AbortSignal): Promise<HeaderResponse> {
  const response = await fetch("/api/snapshot", { signal });
  if (!response.ok) {
    throw new Error(`The service answered ${response.status} ${response.statusText}.`);
  }
  return (await response.json()) as HeaderResponse;
}

export interface ReimportResponse extends HeaderResponse {
  imported: boolean;
}

/** Re-read the workbook at the launch path; identical content keeps the same Snapshot. */
export async function reimportWorkbook(): Promise<ReimportResponse> {
  const response = await fetch("/api/snapshot/reimport", { method: "POST" });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // keep the status line
    }
    throw new Error(detail);
  }
  return (await response.json()) as ReimportResponse;
}
