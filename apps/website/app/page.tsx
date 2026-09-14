import { CliAnimation } from "../components/CliAnimation";
import { REPO_URL, TAGLINE } from "../lib/site";

export default function Home() {
  return (
    <main className="landing">
      <div className="landing-inner">
        <CliAnimation />

        <p className="landing-tagline">{TAGLINE}</p>

        <p className="landing-platforms">discord · slack · notion · google calendar · drive · zoom</p>

        <div className="landing-actions">
          <code className="landing-install select-all">
            git clone {REPO_URL} && cd zipy && just bootstrap
          </code>
          <a href={REPO_URL} className="landing-link">
            github
          </a>
          <a href={`${REPO_URL}/blob/main/deploy/README.md`} className="landing-link">
            self-host
          </a>
          <a href={`${REPO_URL}/blob/main/docs/ARCHITECTURE.md`} className="landing-link">
            docs
          </a>
        </div>
      </div>
    </main>
  );
}
