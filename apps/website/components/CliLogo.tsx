import { CLI_LOGO } from "../lib/cli-frames";

/** The cell the console draws the wordmark with. Everything else is a multiple of it. */
const FILL = "█";

const LINES = CLI_LOGO.split("\n");

/** The bitmap's own size, in cells. Lines are trimmed, so the width is the longest of them. */
const COLUMNS = Math.max(...LINES.map((line) => line.length));
const ROWS = LINES.length;

type Run = { x: number; y: number; width: number };

/**
 * Each unbroken row of filled cells as one rectangle.
 *
 * A rectangle per cell would be 400 of them for the same picture. Merging along the row is
 * enough to bring that under a hundred, and leaves every edge on an integer.
 */
const RUNS: Run[] = LINES.flatMap((line, y) => {
  const runs: Run[] = [];
  let x = 0;
  while (x < line.length) {
    if (line[x] !== FILL) {
      x += 1;
      continue;
    }
    const start = x;
    while (x < line.length && line[x] === FILL) {
      x += 1;
    }
    runs.push({ x: start, y, width: x - start });
  }
  return runs;
});

/**
 * The Zipy wordmark, as the shape the console draws rather than as the text it draws it with.
 *
 * The console has one font and a fixed cell, so block characters and spaces line up there. A
 * browser has neither: the blocks come from one font and the spaces from another, and the moment
 * their advances disagree, or one of them arrives late, every row shifts by a different amount
 * and the letters come apart. Drawing the bitmap as rectangles removes the question. It also
 * makes the wordmark scale exactly, since an SVG with a viewBox has no size of its own and takes
 * whatever the stylesheet gives it.
 */
export function CliLogo() {
  return (
    <svg
      className="cli-logo"
      viewBox={`0 0 ${COLUMNS} ${ROWS}`}
      role="img"
      aria-label="Zipy"
      shapeRendering="crispEdges"
    >
      {RUNS.map(({ x, y, width }) => (
        <rect key={`${x}-${y}`} x={x} y={y} width={width} height={1} />
      ))}
    </svg>
  );
}
