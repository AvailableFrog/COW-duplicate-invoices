import type { HeaderResponse } from "./api";

const numberFormat = new Intl.NumberFormat("en-GB");

export function SnapshotHeaderBar({ header }: { header: HeaderResponse }) {
  const { snapshot, as_of: asOf } = header;
  const issueCount = snapshot.import_issue_count;
  return (
    <dl className="snapshot-header" aria-label="Snapshot">
      <div>
        <dt>Workbook</dt>
        <dd>{snapshot.workbook_name}</dd>
      </div>
      <div>
        <dt>Sheet</dt>
        <dd>{snapshot.sheet}</dd>
      </div>
      <div>
        <dt>Snapshot</dt>
        <dd>
          <code className="fingerprint" title={`${snapshot.fingerprint_algorithm} ${snapshot.fingerprint}`}>
            {snapshot.fingerprint.slice(0, 12)}
          </code>
          <span className="muted"> {snapshot.fingerprint_algorithm}</span>
        </dd>
      </div>
      <div>
        <dt>Rows</dt>
        <dd className="num">
          {numberFormat.format(snapshot.row_count)}
          <span className="muted"> × {snapshot.field_count} fields</span>
        </dd>
      </div>
      <div>
        <dt>Import issues</dt>
        <dd className={issueCount > 0 ? "num unresolved" : "num"}>
          {numberFormat.format(issueCount)}
          {issueCount > 0 ? (
            <details>
              <summary>Show</summary>
              <ul>
                {snapshot.import_issues.map((issue, index) => (
                  <li key={index}>
                    Row {issue.excel_row}: {issue.message}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </dd>
      </div>
      {snapshot.disabled_features.length > 0 ? (
        <div>
          <dt>Disabled</dt>
          <dd className="num unresolved">
            {numberFormat.format(snapshot.disabled_features.length)}
            <span className="muted"> from {snapshot.missing_optional_columns.length} missing columns</span>
            <details>
              <summary>Why</summary>
              <ul>
                {snapshot.disabled_features.map((item) => (
                  <li key={`${item.column}/${item.feature}`}>
                    {item.feature} ({item.kind}): {item.reason}
                  </li>
                ))}
              </ul>
            </details>
          </dd>
        </div>
      ) : null}
      <div>
        <dt>As-of date</dt>
        <dd>
          <time dateTime={asOf.date}>{asOf.date}</time>
          {asOf.is_assumption ? (
            <span className="tag" title={asOf.note}>
              assumed
            </span>
          ) : null}
        </dd>
      </div>
    </dl>
  );
}
