# OpenRAG website

This directory contains the public OpenRAG landing site. It is a Next.js app
that is statically exported for GitHub Pages.

## Local development

Use Node.js 22, then install dependencies and start the development server:

```bash
npm ci
npm run dev
```

The site is available at <http://localhost:3000>.

## Production build

```bash
npm run lint
npm run build
```

The static site is written to `out/`. To test the repository-relative URL used
by GitHub project Pages, build with:

```bash
PAGES_BASE_PATH=/openrag npm run build
```

The workflow in `.github/workflows/deploy-gh-pages.yml` builds this site and the
Docusaurus project in `docs/`, merges both static exports, and publishes one
GitHub Pages artifact. The landing site owns `/`; documentation
keeps its existing routes, with its homepage at `/docs/`.

The deployment defaults to `docs.openr.ag`. Set the repository variables
`PAGES_CNAME=www.openr.ag` and `PAGES_SITE_URL=https://www.openr.ag` for the
final hostname cutover. Until `PAGES_CNAME` is explicitly set, CI validates the
merged artifact but deploys the original docs-only build, keeping the live docs
site unchanged.
