import { useEffect, useState } from "react";

import type { AsOf, HeaderResponse } from "./api";

const numberFormat = new Intl.NumberFormat("en-GB");

interface SnapshotHeaderBarProps {
  header: HeaderResponse;
  onAsOfChange: (date: string) => Promise<void>;
}

export function SnapshotHeaderBar({ header, onAsOfChange }: SnapshotHeaderBarProps) {
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
          <AsOfControl asOf={asOf} onChange={onAsOfChange} />
        </dd>
      </div>
    </dl>
  );
}

/** The analytical as-of date, always labelled as an assumption, which the analyst can change. */
function AsOfControl({ asOf, onChange }: { asOf: AsOf; onChange: (date: string) => Promise<void> }) {
  const [draft, setDraft] = useState(asOf.date);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  // Follow the date in effect when it changes elsewhere, such as after a reimport.
  useEffect(() => setDraft(asOf.date), [asOf.date]);

  async function apply(date: string) {
    setSaving(true);
    setError("");
    try {
      await onChange(date);
      setDraft(date);
    } catch (failure: unknown) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      className="as-of"
      onSubmit={(event) => {
        event.preventDefault();
        if (draft) void apply(draft);
      }}
    >
      <input
        type="date"
        aria-label="Analytical as-of date"
        value={draft}
        required
        onChange={(event) => setDraft(event.target.value)}
      />
      <span className="tag" title={asOf.note}>
        assumed
      </span>
      {draft !== asOf.date ? (
        <button type="submit" className="secondary" disabled={saving}>
          Apply
        </button>
      ) : null}
      {!asOf.is_default ? (
        <button type="button" className="secondary" disabled={saving} onClick={() => void apply(asOf.default)}>
          Reset to {asOf.default}
        </button>
      ) : null}
      <span className="muted as-of-note">{asOf.note}</span>
      {error ? (
        <span className="error" role="alert">
          {error}
        </span>
      ) : null}
    </form>
  );
}
