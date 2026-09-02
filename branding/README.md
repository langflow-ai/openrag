# BomaRAG branding

All upstream OpenRAG artwork has been removed. What ships today are neutral
placeholder marks. Drop the official Bomalogic Automation assets in and update
the files below.

## Swap points

| Asset | File | Notes |
| --- | --- | --- |
| App logo (header, login, onboarding) | `frontend/components/icons/bomarag-logo.tsx` | Inline SVG React component. Keep `fill`/`stroke` as `currentColor` so it inherits the theme. |
| Docs navbar logo (light) | `docs/static/img/logo-bomarag-docs-light.svg` | ~220x48 wordmark. |
| Docs navbar logo (dark) | `docs/static/img/logo-bomarag-docs-dark.svg` | Same geometry, light fill. |
| Square mark (README, social) | `docs/static/img/bomarag-logo.svg` | 1:1 viewBox. |
| App favicon | `frontend/app/favicon.ico` | Still the upstream icon — **replace before shipping.** |
| Docs favicon | `docs/static/img/favicon.ico` | Still the upstream icon — **replace before shipping.** |

## Screenshots and demo media

These are upstream captures of the OpenRAG UI and still show the old branding.
Re-capture from a running BomaRAG instance before any public launch:

- `docs/static/img/bomarag_readme_downsized.gif` (README hero)
- `docs/static/img/chat_bomarag.png`
- `docs/static/img/add_knowledge_bomarag.png`
- `docs/static/img/bomarag_tui_dec_2025.png`
- `docs/static/img/uv_run_bomarag.png`
- `docs/static/img/bomarag-containers.png`

## Colors

The frontend theme lives in `frontend/app/globals.css` as HSL custom properties.
To apply the Bomalogic palette, change these tokens in both the `:root` (light)
and `.dark` blocks — everything else derives from them:

```
--primary              /* brand action color  */
--primary-foreground   /* text on --primary   */
--primary-hover
--accent
--accent-foreground
```

Values are space-separated HSL **without** the `hsl()` wrapper, e.g.
`--primary: 221 83% 53%;`. Convert your hex codes to HSL before pasting.

Docs colors live in `docs/src/css/custom.css` (`--ifm-color-primary*`).
