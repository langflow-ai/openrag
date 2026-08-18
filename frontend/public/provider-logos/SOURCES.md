# Provider marks

Vendor logos for the model picker's provider groups
(`app/settings/_components/model-picker.tsx`).

## Where they came from

Copied byte-for-byte from LiteLLM's own admin dashboard:

    https://github.com/BerriAI/litellm
    ui/litellm-dashboard/public/assets/logos/
    commit 02746eb122bd05c7ef0d47d94a9c5c55cd2b8fa8

The provider -> file mapping is LiteLLM's too, derived from `providerLogoMap`
joined with `provider_map` in
`ui/litellm-dashboard/src/components/provider_info_helpers.tsx`, and lives in
`app/settings/_lib/provider-logos.ts`. Taking both from the same place is the
point: our provider keys *are* LiteLLM's `litellm_provider` values, so the
mapping stays correct without a second judgement call about which mark belongs
to which key.

Vendored rather than hotlinked because the app has to render in an air-gapped
cluster, and rather than pulled from the installed `litellm` wheel because
these files are not shipped in it -- they exist only in the repo's dashboard
sources.

## Why only 41 files

They cover 63 of the 90 providers that carry models (2,084 of 2,297 models).
The rest render a two-letter monogram tile. Redrawing or approximating a
vendor's mark is worse than showing none -- the same reasoning already recorded
in `app/settings/_lib/providers.tsx`.

## Updating

These are third-party trademarks, used to identify each vendor's own models.
When bumping LiteLLM, re-copy any changed files from the path above and
regenerate the map from the same commit so the two cannot drift.
