import Link from "next/link";

export default function NotFound() {
  return (
    <main className="landing">
      <div className="landing-inner">
        <p className="landing-tagline">not found</p>
        <Link href="/" className="landing-link">
          back home
        </Link>
      </div>
    </main>
  );
}
