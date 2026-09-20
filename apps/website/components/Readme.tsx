import { readFileSync } from "node:fs";
import { join } from "node:path";
import { marked } from "marked";
import { REPO_URL } from "../lib/site";

/** The repository's own README, three levels above apps/website. */
const SOURCE = join(process.cwd(), "..", "..", "README.md");

/** Where a link that points inside the repository goes once it is off GitHub. */
const BLOB = `${REPO_URL}/blob/main/`;
const RAW = `${REPO_URL.replace("github.com", "raw.githubusercontent.com")}/main/`;

/**
 * Repository-relative links and images, pointed back at GitHub.
 *
 * The README is written to be read on GitHub, where `docs/ARCHITECTURE.md` resolves. Served from
 * the site's root it resolves to nothing, so every path that is not already absolute and not a
 * fragment is rewritten. A link keeps its rendered form and gets a new destination.
 */
function absolute(html: string) {
  return html.replace(
    /(href|src)="([^"]+)"/g,
    (whole, attribute: string, target: string) => {
      if (/^([a-z]+:|\/\/|#)/i.test(target)) {
        return whole;
      }
      const base = attribute === "src" ? RAW : BLOB;
      return `${attribute}="${base}${target.replace(/^\.?\//, "")}"`;
    },
  );
}

/**
 * The README, rendered into a panel.
 *
 * Read from the file rather than from the GitHub API, so the page is static, has nothing to
 * fetch and cannot show a different README from the commit it was built at. The markup comes
 * from a file in this repository at build time, never from a request.
 */
export function Readme() {
  const markdown = readFileSync(SOURCE, "utf8");
  const html = absolute(marked.parse(markdown, { async: false, gfm: true }));
  return (
    <section className="readme" aria-label="README">
      <header className="readme-bar">
        <span className="readme-dot" />
        <span className="readme-dot" />
        <span className="readme-dot" />
        <span className="readme-name">README.md</span>
      </header>
      <div className="readme-body">
        <article
          className="readme-prose"
          // Build-time content from this repository's own README, not from a request.
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </div>
    </section>
  );
}
