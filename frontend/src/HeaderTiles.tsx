import type { TilesResponse } from "./api";

const numberFormat = new Intl.NumberFormat("en-GB");
const percentFormat = new Intl.NumberFormat("en-GB", { style: "percent", maximumFractionDigits: 1 });

/** The Overview header tiles, each a registry metric with its definition one step away. */
export function HeaderTiles({ data }: { data: TilesResponse }) {
  return (
    <section className="tiles" aria-labelledby="tiles-heading">
      <h2 id="tiles-heading" className="visually-hidden">
        Scale of the Snapshot
      </h2>
      <ul>
        {data.tiles.map((tile) => (
          <li key={tile.metric_id} className="tile">
            <span className="tile-label">{tile.label}</span>
            <span className="tile-value num">{tile.value === null ? "—" : numberFormat.format(tile.value)}</span>
            {tile.percentage && tile.percentage.ratio !== null ? (
              <span className="muted tile-share num">
                {percentFormat.format(tile.percentage.ratio)} ({numberFormat.format(tile.percentage.numerator)} of{" "}
                {numberFormat.format(tile.percentage.denominator)} Tickets)
              </span>
            ) : null}
            <details>
              <summary>Definition</summary>
              <p>{tile.definition}</p>
              <p className="muted">
                Metric <code>{tile.metric_id}</code>, registry {data.versions.registry}
              </p>
            </details>
            {tile.warnings.map((warning) => (
              <p key={warning} className="unresolved">
                {warning}
              </p>
            ))}
          </li>
        ))}
      </ul>
      <p className="muted tiles-note">{data.note}</p>
    </section>
  );
}
