"use client";

import { useEffect, useRef, useState } from "react";
import { CLI_FRAMES, CLI_LOGO } from "../lib/cli-frames";

/** Largest the logo is ever drawn, in px. */
const MAX_FONT_PX = 18;

/** Smallest the logo is drawn before it stops shrinking, in px. */
const MIN_FONT_PX = 4;

/** Share of the viewport height the logo may take, leaving room for the tagline and the links. */
const HEIGHT_SHARE = 0.46;

/** Size the probe is fixed at in the stylesheet. Any size works; it yields the ratio used. */
const PROBE_PX = 100;

/** Columns and rows of the widest and tallest frame, which is not always the one it settles on. */
const COLUMNS = Math.max(
  ...[...CLI_FRAMES.map((frame) => frame.text), CLI_LOGO].map((text) =>
    Math.max(...text.split("\n").map((line) => line.length)),
  ),
);
const ROWS = Math.max(
  ...[...CLI_FRAMES.map((frame) => frame.text), CLI_LOGO].map(
    (text) => text.split("\n").length,
  ),
);

/** A block that bounds every frame, so no frame of the animation can overflow the fit. */
export const PROBE_TEXT = Array.from({ length: ROWS }, () =>
  "\u2588".repeat(COLUMNS),
).join("\n");

/**
 * The font size at which the logo fits the space, from its measured size rather than an assumed
 * character advance. A monospace fallback with a wider advance than the webfont clips a logo
 * sized by arithmetic; measuring the glyphs that actually rendered cannot.
 */
export function fittedSize(
  probe: HTMLElement,
  availableWidth: number,
  availableHeight: number,
) {
  probe.style.minHeight = "0";
  probe.style.fontSize = `${PROBE_PX}px`;
  const widthPerPx = probe.scrollWidth / PROBE_PX;
  const heightPerPx = probe.scrollHeight / PROBE_PX;
  if (widthPerPx <= 0 || heightPerPx <= 0) {
    return MAX_FONT_PX;
  }
  const fits = Math.min(
    availableWidth / widthPerPx,
    availableHeight / heightPerPx,
  );
  return Math.max(MIN_FONT_PX, Math.min(MAX_FONT_PX, fits));
}

/**
 * Plays the ASCII logo animation the Zipy console opens with, as preformatted text, once, and
 * holds on the logo. Each frame keeps the duration it was drawn with.
 */
export function CliAnimation() {
  // One past the last frame is the settled logo.
  const [frame, setFrame] = useState(0);
  const settled = frame >= CLI_FRAMES.length;
  const stage = useRef<HTMLDivElement>(null);
  const probe = useRef<HTMLPreElement>(null);
  const shown = useRef<HTMLPreElement>(null);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      // With reduced motion the logo is shown after one tick.
      const id = window.setTimeout(() => setFrame(CLI_FRAMES.length), 0);
      return () => window.clearTimeout(id);
    }

    let timer = 0;
    const step = (index: number) => {
      setFrame(index);
      if (index < CLI_FRAMES.length) {
        timer = window.setTimeout(() => step(index + 1), CLI_FRAMES[index].ms);
      }
    };
    step(0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    const fit = () => {
      const box = stage.current;
      const measured = probe.current;
      const pre = shown.current;
      if (!box || !measured || !pre) {
        return;
      }
      const size = fittedSize(
        measured,
        box.clientWidth,
        window.innerHeight * HEIGHT_SHARE,
      );
      pre.style.fontSize = `${size}px`;
    };

    // A webfont swapping in changes the glyph advance and so the size that fits, and the swap
    // lands after the promise resolves, so measure on the frame after it.
    let frame = 0;
    const refit = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        frame = requestAnimationFrame(fit);
      });
    };

    fit();
    refit();
    const observer = new ResizeObserver(fit);
    if (stage.current) {
      observer.observe(stage.current);
    }
    window.addEventListener("resize", fit);
    window.addEventListener("orientationchange", fit);
    const fonts = document.fonts;
    fonts?.ready.then(refit).catch(() => undefined);
    fonts?.addEventListener?.("loadingdone", refit);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", fit);
      window.removeEventListener("orientationchange", fit);
      fonts?.removeEventListener?.("loadingdone", refit);
    };
  }, []);

  return (
    <div ref={stage} className="cli-stage">
      <pre ref={probe} className="cli-animation cli-probe" aria-hidden="true">
        {PROBE_TEXT}
      </pre>
      <pre
        ref={shown}
        aria-label="Zipy"
        className={`cli-animation cli-shown select-none${settled ? " is-settled" : ""}`}
      >
        {settled ? CLI_LOGO : CLI_FRAMES[frame].text}
      </pre>
    </div>
  );
}
