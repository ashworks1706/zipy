import { CliLogo } from "../components/CliLogo";
import { FlagStrips } from "../components/FlagStrips";
import { Readme } from "../components/Readme";
import { REPO_URL, TAGLINE } from "../lib/site";

export default function Home() {
  return (
    <>
      <FlagStrips />

      <main className="page">
        <section className="landing">
          <div className="landing-inner">
            <CliLogo />

            <p className="landing-tagline">{TAGLINE}</p>

            <div className="landing-actions">
              <code className="landing-install select-all">
                git clone {REPO_URL} && cd zipy && just bootstrap
              </code>
              <a href={REPO_URL} className="landing-link">
                github
              </a>
              <a
                href={`${REPO_URL}/blob/main/docs/ARCHITECTURE.md`}
                className="landing-link"
              >
                docs
              </a>
            </div>
          </div>
        </section>

        <Readme />
      </main>
    </>
  );
}
