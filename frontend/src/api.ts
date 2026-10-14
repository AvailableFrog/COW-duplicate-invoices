// Types mirror the JSON the Python API returns. Every numeric response carries
// the Snapshot fingerprint and the as-of date in effect.

export interface ImportIssue {
  code: string;
  message: string;
  excel_row?: number;
  field?: string;
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
