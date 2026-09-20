import type { CSSProperties } from "react";

/** Squares across one field. Column 0 is the outer edge, whichever side the field sits on. */
const COLUMNS = 12;

/** Rows generated. The cell is a fixed square, so this covers the tallest viewport and the rest
    is clipped. Fixed, so the pattern does not reflow as the viewport changes. */
const ROWS = 110;

/** How fast the scatter thins out. Above one it clears quickly and leaves stragglers. */
const FALLOFF = 1.6;

type Square = { row: number; column: number; seed: number };

/**
 * A value in [0, 1) for one cell. Integer operations only, so the server and the browser agree
 * and the markup they each produce is the same.
 */
function noise(row: number, column: number) {
  let hash = (row * 73856093) ^ (column * 19349663);
  hash = Math.imul(hash ^ (hash >>> 15), 2246822519);
  hash = Math.imul(hash ^ (hash >>> 13), 3266489917);
  return ((hash ^ (hash >>> 16)) >>> 0) / 4294967296;
}

/**
 * The squares of one field: a checkerboard against the edge, thinning into loose blocks inward.
 *
 * Every square sits on the checkerboard lattice, so the scatter still reads as a flag coming
 * apart rather than as noise. Which of them survive is decided per cell and does not change
 * between renders.
 */
const SQUARES: Square[] = Array.from({ length: ROWS }, (_, row) =>
  Array.from({ length: COLUMNS }, (_, column) => ({
    row,
    column,
    // A second value per cell, so how long a square takes to settle and when it blinks are not
    // the same number that decided whether it exists at all.
    seed: noise(column, row),
  })),
)
  .flat()
  .filter(
    ({ row, column }) =>
      (row + column) % 2 === 0 &&
      noise(row, column) < (1 - column / (COLUMNS - 1)) ** FALLOFF,
  );

function Field({ side }: { side: "left" | "right" }) {
  return (
    <div className={`flag flag-${side}`} aria-hidden="true">
      {SQUARES.map(({ row, column, seed }) => (
        <span
          key={`${row}-${column}`}
          className="flag-square"
          style={
            {
              gridRow: row + 1,
              gridColumn: column + 1,
              "--column": column,
              "--row": row,
              "--seed": seed,
            } as CSSProperties
          }
        />
      ))}
    </div>
  );
}

/**
 * Two checkered fields that race in from the edges on load and scatter toward the middle.
 *
 * Decoration only. Every square is the same colour; the fade across the field is a mask rather
 * than a value per square, so the falloff does not have to be kept in step with the number of
 * columns. Each square carries a seed the stylesheet uses to settle and blink off its neighbours.
 */
export function FlagStrips() {
  return (
    <>
      <Field side="left" />
      <Field side="right" />
    </>
  );
}
