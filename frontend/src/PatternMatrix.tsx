import type {
  MatrixRow,
  PatternFilterPayload,
  PatternFilterState,
  PatternId,
  PatternMatrix as Matrix,
  SourceStateId,
} from "./api";

type Select = (selection: PatternFilterState) => void;

function plural(count: number, one: string, many: string): string {
  return `${count.toLocaleString()} ${count === 1 ? one : many}`;
}

function isOnly<T>(list: T[], value: T | null): boolean {
  return value === null ? list.length === 0 : list.length === 1 && list[0] === value;
}

/** One count; a nonzero count is a button that shows its tickets in the list below. */
function CountCell({
  count,
  label,
  selection,
  current,
  onSelect,
}: {
  count: number;
  label: string;
  selection: PatternFilterState;
  current: PatternFilterState;
  onSelect: Select;
}) {
  if (count === 0) return <td className="num matrix-zero">0</td>;
  // Pressed while the list shows exactly this count; with no pattern filter nothing is pressed.
  const pressed =
    (current.patterns.length > 0 || current.sourceStates.length > 0) &&
    isOnly(current.patterns, selection.patterns[0] ?? null) &&
    isOnly(current.sourceStates, selection.sourceStates[0] ?? null);
  return (
    <td className="num">
      <button
        type="button"
        className="matrix-count"
        aria-pressed={pressed}
        aria-label={`${count.toLocaleString()} ${label}: show in the list`}
        onClick={() => onSelect(selection)}
      >
        {count.toLocaleString()}
      </button>
    </td>
  );
}

/**
 * The pattern-by-source-state count matrix: distinct in-filter tickets per pattern and source state. Rows overlap,
 * because one ticket can carry several patterns, so the caption says so and the Any pattern row counts each once.
 */
export function PatternMatrix({
  matrix,
  current,
  onSelect,
}: {
  matrix: Matrix;
  current: PatternFilterState;
  onSelect: Select;
}) {
  // The unreadable-state column only appears when some ticket is in it; every other column always shows.
  const states = matrix.source_states.filter(
    (state) =>
      state.id !== "unreadable" ||
      [...matrix.rows, matrix.any_pattern].some((row) => row.cells.some((c) => c.source_state === state.id && c.tickets > 0)),
  );
  const row = (cells: MatrixRow, pattern: PatternId | null, name: string) => {
    const patterns = pattern ? [pattern] : [];
    const counts = new Map(cells.cells.map((cell) => [cell.source_state, cell.tickets]));
    return (
      <>
        {states.map((state) => (
          <CountCell
            key={state.id}
            count={counts.get(state.id) ?? 0}
            label={`${state.label} ${(counts.get(state.id) ?? 0) === 1 ? "ticket" : "tickets"}, ${name}`}
            selection={{ patterns, sourceStates: [state.id] }}
            current={current}
            onSelect={onSelect}
          />
        ))}
        <CountCell
          count={cells.tickets}
          label={`${cells.tickets === 1 ? "ticket" : "tickets"} in any state, ${name}`}
          selection={{ patterns, sourceStates: [] }}
          current={current}
          onSelect={onSelect}
        />
        <td className="num">{cells.possible_duplicates.toLocaleString()}</td>
      </>
    );
  };
  return (
    <div className="pattern-matrix">
      <div className="table-scroll">
        <table>
          <caption>{matrix.caption}</caption>
          <thead>
            <tr>
              <th scope="col">Pattern</th>
              {states.map((state) => (
                <th scope="col" key={state.id} title={state.definition}>
                  {state.label}
                </th>
              ))}
              <th scope="col">Tickets</th>
              <th scope="col">Possible duplicates</th>
            </tr>
          </thead>
          <tbody>
            {matrix.rows.map((pattern) => (
              <tr key={pattern.pattern.id}>
                <th scope="row">
                  {pattern.pattern.number}. {pattern.pattern.label}
                </th>
                {row(pattern, pattern.pattern.id, pattern.pattern.label)}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">Any pattern, each ticket once</th>
              {row(matrix.any_pattern, null, "any pattern")}
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="muted matrix-note">
        {matrix.note} Grain: {matrix.grain}. Choose a count to list those tickets' possible duplicates.
      </p>
    </div>
  );
}

/** The multi-label pattern filter: each pattern's own counts, and the union the list holds. */
export function PatternFilter({
  payload,
  current,
  stateLabels,
  onSelect,
}: {
  payload: PatternFilterPayload;
  current: PatternFilterState;
  stateLabels: Map<SourceStateId, string>;
  onSelect: Select;
}) {
  const toggle = (pattern: PatternId, on: boolean) => {
    const patterns = on ? [...current.patterns, pattern] : current.patterns.filter((id) => id !== pattern);
    onSelect({ ...current, patterns });
  };
  const chosen = payload.counts.filter((count) => count.selected);
  const sum = (key: "possible_duplicates" | "tickets") => chosen.reduce((total, count) => total + count[key], 0);
  return (
    <fieldset className="pattern-filter">
      <legend>Show patterns</legend>
      <p className="muted">Choose one or more; the list shows possible duplicates matching any of them.</p>
      <ul>
        {payload.counts.map((count) => (
          <li key={count.id}>
            <label>
              <input
                type="checkbox"
                checked={current.patterns.includes(count.id)}
                onChange={(event) => toggle(count.id, event.currentTarget.checked)}
                aria-describedby={`pattern-count-${count.id}`}
              />
              {count.label}
            </label>
            <span className="muted num" id={`pattern-count-${count.id}`}>
              {plural(count.possible_duplicates, "possible duplicate", "possible duplicates")},{" "}
              {plural(count.tickets, "ticket", "tickets")}
            </span>
          </li>
        ))}
      </ul>
      {current.sourceStates.length > 0 ? (
        <p className="pattern-state">
          Only tickets that are {current.sourceStates.map((id) => stateLabels.get(id) ?? id).join(" or ")}.{" "}
          <button type="button" className="secondary" onClick={() => onSelect({ ...current, sourceStates: [] })}>
            Any source state
          </button>
        </p>
      ) : null}
      <p className="pattern-totals" role="status">
        {payload.active ? "Matching: " : "All: "}
        <strong className="num">{plural(payload.totals.possible_duplicates, "possible duplicate", "possible duplicates")}</strong>{" "}
        with <strong className="num">{plural(payload.totals.tickets, "ticket", "tickets")}</strong> inside the filters, each
        counted once.
        {chosen.length > 1
          ? ` The ${chosen.length} patterns' own counts add up to ${sum("possible_duplicates").toLocaleString()} and ${sum("tickets").toLocaleString()}: they overlap.`
          : null}
      </p>
      <p className="muted">{payload.note}</p>
      {payload.active ? (
        <button type="button" className="secondary" onClick={() => onSelect({ patterns: [], sourceStates: [] })}>
          Clear pattern filter
        </button>
      ) : null}
    </fieldset>
  );
}
