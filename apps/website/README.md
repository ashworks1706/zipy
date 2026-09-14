# website

The Zipy landing page: Next.js 16 (App Router), React 19, Tailwind 4, TypeScript. One page, the
console's logo animation, and links to the repo. No blog.

```
just web-setup     # npm ci
just web           # dev server at http://localhost:3000
just web-build     # production build
just web-preview   # build, then serve it
just web-frames    # regenerate lib/cli-frames.ts from apps/cli/assets
just check-website # eslint and tsc
```

`lib/cli-frames.ts` is generated; edit the ASCII Motion exports in `apps/cli/assets` and run
`just web-frames`. Set `NEXT_PUBLIC_SITE_URL` to the deployed origin for metadata, the sitemap and
robots. Deploys to Vercel or any Node host; it is not part of the Docker image.
