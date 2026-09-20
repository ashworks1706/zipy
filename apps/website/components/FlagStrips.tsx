import type { CSSProperties } from "react";

/** Squares across one strip. The outermost is column 0, whichever edge the strip sits on. */
const COLUMNS = 7;

/** Squares down one strip. Fixed, so the pattern does not reflow as the viewport changes. */
const ROWS = 22;

type Square = { row: number; column: number };

/** The filled half of the checkerboard. The other half is the ground showing through. */
const SQUARES: Square[] = Array.from({ length: ROWS }, (_, row) =>
  Array.from({ length: COLUMNS }, (_, column) => ({ row, column })),
)
  .flat()
  .filter(({ row, column }) => (row + column) % 2 === 0);

function Strip({ side }: { side: "left" | "right" }) {
  return (
    <div className={`flag flag-${side}`} aria-hidden="true">
      {SQUARES.map(({ row, column }) => (
        <span
          key={`${row}-${column}`}
          className="flag-square"
          style={
            {
              gridRow: row + 1,
              gridColumn: column + 1,
              "--column": column,
              "--row": row,
            } as CSSProperties
          }
        />
      ))}
    </div>
  );
}

/**
 * Two checkered strips that race in from the edges on load and fade out toward the middle.
 *
 * Decoration only. Every square is the same colour and opacity; the dissipation is a mask on the
 * strip rather than a value per square, so the falloff does not have to be kept in step with the
 * number of columns.
 */
export function FlagStrips() {
  return (
    <>
      <Strip side="left" />
      <Strip side="right" />
    </>
  );
}
