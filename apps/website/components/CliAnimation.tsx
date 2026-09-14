"use client";

import { useEffect, useState } from "react";
import { CLI_FRAMES, CLI_LOGO } from "../lib/cli-frames";

/**
 * Plays the ASCII logo animation the Zipy console opens with, as preformatted text, once, and
 * holds on the logo. Each frame keeps the duration it was drawn with.
 */
export function CliAnimation() {
  // One past the last frame is the settled logo.
  const [frame, setFrame] = useState(0);
  const settled = frame >= CLI_FRAMES.length;

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

  return (
    <pre aria-label="Zipy" className={`cli-animation select-none${settled ? " is-settled" : ""}`}>
      {settled ? CLI_LOGO : CLI_FRAMES[frame].text}
    </pre>
  );
}
