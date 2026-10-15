import { useId, useRef, useState } from "react";

import { activateUpload, uploadWorkbook, UploadRefusal, type ReimportResponse, type UploadPreview } from "./api";

interface WorkbookImportProps {
  /** Called once a previewed workbook is the active Snapshot. */
  onActivated: (result: ReimportResponse) => void;
}

type ImportState =
  | { kind: "idle" }
  | { kind: "reading"; name: string }
  | { kind: "previewing"; preview: UploadPreview }
  | { kind: "activating"; preview: UploadPreview }
  | { kind: "refused"; name: string; message: string; nextStep: string };

const sizeFormat = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 });

function size(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${sizeFormat.format(bytes / (1024 * 1024))} MB` : `${sizeFormat.format(bytes / 1024)} KB`;
}

/**
 * Import a workbook from the browser (ticket #41): choose an .xlsx file, see what the service would read from it,
 * then make it the active Snapshot. Nothing changes until "Make it the active Snapshot"; a workbook the launch would
 * refuse is refused here with the same message.
 */
export function WorkbookImport({ onActivated }: WorkbookImportProps) {
  const [state, setState] = useState<ImportState>({ kind: "idle" });
  const [status, setStatus] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const hintId = useId();

  async function choose(file: File | undefined) {
    if (!file) return;
    setStatus("");
    setState({ kind: "reading", name: file.name });
    try {
      setState({ kind: "previewing", preview: await uploadWorkbook(file) });
    } catch (error: unknown) {
      setState({
        kind: "refused",
        name: file.name,
        message: error instanceof Error ? error.message : String(error),
        nextStep: error instanceof UploadRefusal ? error.nextStep : "",
      });
    } finally {
      if (input.current) input.current.value = "";
    }
  }

  async function activate(preview: UploadPreview) {
    setState({ kind: "activating", preview });
    try {
      const result = await activateUpload(preview.id);
      setState({ kind: "idle" });
      setStatus(
        result.imported
          ? `${preview.workbook_name} is now the active Snapshot ${result.snapshot.fingerprint.slice(0, 12)}; the earlier Snapshots are unchanged.`
          : `${preview.workbook_name} has the same content as Snapshot ${result.snapshot.fingerprint.slice(0, 12)}, which is now active.`,
      );
      onActivated(result);
    } catch (error: unknown) {
      setState({
        kind: "refused",
        name: preview.workbook_name,
        message: error instanceof Error ? error.message : String(error),
        nextStep: error instanceof UploadRefusal ? error.nextStep : "",
      });
    }
  }

  const preview = state.kind === "previewing" || state.kind === "activating" ? state.preview : null;
  return (
    <section className="workbook-import" aria-labelledby="workbook-import-heading">
      <h2 id="workbook-import-heading" className="visually-hidden">
        Import a workbook
      </h2>
      <label className="file-choice">
        Import a workbook (.xlsx)
        <input
          ref={input}
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          aria-describedby={hintId}
          disabled={state.kind === "reading" || state.kind === "activating"}
          onChange={(event) => choose(event.target.files?.[0])}
        />
      </label>
      <span id={hintId} className="muted">
        Previewed before anything changes; kept in the local data directory and never sent anywhere else.
      </span>
      <p className="status" role="status">
        {state.kind === "reading" ? `Reading ${state.name}…` : state.kind === "activating" ? "Activating…" : status}
      </p>
      {state.kind === "refused" ? (
        <div className="notice notice-error" role="alert">
          <p>
            <strong>{state.name} was not imported:</strong> {state.message}.
          </p>
          {state.nextStep ? <p>{state.nextStep}</p> : null}
        </div>
      ) : null}
      {preview ? <PreviewPanel preview={preview} busy={state.kind === "activating"} onActivate={activate} onCancel={() => setState({ kind: "idle" })} /> : null}
    </section>
  );
}

interface PreviewPanelProps {
  preview: UploadPreview;
  busy: boolean;
  onActivate: (preview: UploadPreview) => void;
  onCancel: () => void;
}

function PreviewPanel({ preview, busy, onActivate, onCancel }: PreviewPanelProps) {
  const present = preview.mapping.filter((item) => item.present).length;
  return (
    <section className="upload-preview" aria-labelledby="upload-preview-heading">
      <h3 id="upload-preview-heading">Preview of {preview.workbook_name}</h3>
      {preview.same_as ? (
        <p className="notice">
          This is the same content as {preview.same_as === "active" ? "the active Snapshot" : "a Snapshot already imported"}{" "}
          <code>{preview.fingerprint.slice(0, 12)}</code>, so making it active adds nothing new.
        </p>
      ) : null}
      <dl className="preview-facts">
        <dt>Sheet</dt>
        <dd>{preview.sheet}</dd>
        <dt>Rows</dt>
        <dd>{preview.row_count.toLocaleString("en-GB")} tickets</dd>
        <dt>Fields</dt>
        <dd>
          {preview.field_count} ({present} of {preview.mapping.length} expected columns found
          {preview.other_columns.length ? `, ${preview.other_columns.length} other kept as recorded` : ""})
        </dd>
        <dt>Import issues</dt>
        <dd>
          {preview.import_issue_count === 0
            ? "None"
            : `${preview.import_issue_count.toLocaleString("en-GB")}: ${preview.import_issue_counts.map((item) => `${item.count} ${item.code.replaceAll("_", " ")}`).join(", ")}`}
        </dd>
        <dt>File</dt>
        <dd>
          {size(preview.size_bytes)}, {preview.fingerprint_algorithm} <code>{preview.fingerprint.slice(0, 12)}</code>
        </dd>
      </dl>
      {preview.disabled_features.length ? (
        <div className="notice">
          <p>Missing optional columns turn these features off:</p>
          <ul>
            {preview.disabled_features.map((feature) => (
              <li key={`${feature.column}:${feature.feature}`}>{feature.reason}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <details>
        <summary>Column mapping</summary>
        <div className="table-scroll" role="region" aria-label="Column mapping, scrollable" tabIndex={0}>
          <table className="evidence-table">
            <thead>
              <tr>
                <th scope="col">Expected column</th>
                <th scope="col">Needed</th>
                <th scope="col">Found in column</th>
              </tr>
            </thead>
            <tbody>
              {preview.mapping.map((item) => (
                <tr key={item.column}>
                  <th scope="row">{item.column}</th>
                  <td>{item.kind === "required" ? "Required" : "Optional"}</td>
                  <td>{item.present ? item.position : <span className="unresolved">Missing</span>}</td>
                </tr>
              ))}
              {preview.other_columns.map((column) => (
                <tr key={`other:${column}`}>
                  <th scope="row">{column}</th>
                  <td>Not used</td>
                  <td>Kept as recorded</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      {preview.import_issues.length ? (
        <details>
          <summary>
            Import issues{preview.import_issue_count > preview.import_issues.length ? ` (first ${preview.import_issues.length})` : ""}
          </summary>
          <ul>
            {preview.import_issues.map((issue, index) => (
              <li key={index}>
                Row {issue.excel_row}
                {issue.field ? `, ${issue.field}` : ""}: {issue.message}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <p className="muted">
        Kept at <code>{preview.stored_as}</code>. Reimport still reads the workbook the service was launched with.
      </p>
      <div className="form-actions">
        <button type="button" disabled={busy} onClick={() => onActivate(preview)}>
          Make it the active Snapshot
        </button>
        <button type="button" className="secondary" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
  );
}
