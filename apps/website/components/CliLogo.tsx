"use client";

import { useEffect, useRef } from "react";
import { CLI_LOGO } from "../lib/cli-frames";

/** Largest the wordmark is ever drawn, in px. */
const MAX_FONT_PX = 11;

/** Smallest the wordmark is drawn before it stops shrinking, in px. */
const MIN_FONT_PX = 3;

/** Share of the viewport height the wordmark may take, leaving room for the tagline and links. */
const HEIGHT_SHARE = 0.26;

/** Size the probe is fixed at in the stylesheet. Any size works; it yields the ratio used. */
const PROBE_PX = 100;

/**
 * The font size at which the wordmark fits the space, from its measured size rather than an
 * assumed character advance. A monospace fallback with a wider advance than the webfont clips a
 * wordmark sized by arithmetic; measuring the glyphs that actually rendered cannot.
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
 * The Zipy wordmark, as the preformatted block text the console settles on. It does not animate:
 * the size it is drawn at depends on the font that rendered, so a sequence of frames drawn while
 * that is still settling reads differently at different widths.
 */
export function CliLogo() {
  const stage = useRef<HTMLDivElement>(null);
  const probe = useRef<HTMLPreElement>(null);
  const shown = useRef<HTMLPreElement>(null);

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
      <pre ref={probe} className="cli-logo cli-probe" aria-hidden="true">
        {CLI_LOGO}
      </pre>
      <pre ref={shown} aria-label="Zipy" className="cli-logo select-none">
        {CLI_LOGO}
      </pre>
    </div>
  );
}
