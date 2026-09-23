# readme-lies

**Your README is lying. This catches it in CI.**

```console
$ uvx --from git+https://github.com/sandeepsirodia/readme-lies readme-lies
README.md:42: `npm run dev` — no "dev" script in package.json
README.md:77: […](docs/setup.md) — file does not exist
docs/api.md:12: […](#client-instances) — no heading with that anchor
docs/api.md:30: `createClient()` — `createClient` is not in the code (renamed or removed?)
4 lie(s) found.
```

Docs rot silently. The script got renamed, the heading got reworded, the function moved, and the README still says the old thing. Humans shrug. **Coding agents believe it**, and burn your tokens running commands that don't exist.

## It finds real bugs in popular repos

I ran it on 27 well-known repositories. Every finding below was checked by hand, and every one is a real broken reference on `main`: 11 in 4 repos:

| Repo | Real lies found | Example |
|---|---|---|
| encode/httpx | 7 | `[Client instance](#client-instances)`: heading was renamed |
| pydantic/pydantic | 1 | link to `#customise-settings-sources` on a page that's now a stub |
| astral-sh/uv | 1 | `init.md#unpackaged-applications`: no such section |
| fastapi/typer | 2 | root README links `tutorial/install.md`, which lives in `docs/` |

**Precision:** on 12 repos it had never seen during development, 10 of 12 findings were real (83%). The two false alarms (dunder names inside code-span headings) are now fixed and covered by a regression test, like every other false alarm found so far.

## Install

```bash
uvx --from git+https://github.com/sandeepsirodia/readme-lies readme-lies   # run once
uv tool install git+https://github.com/sandeepsirodia/readme-lies          # or keep it
```

One Python file, zero dependencies, no LLM, no network.

### GitHub Action

```yaml
# .github/workflows/docs.yml
on: [push, pull_request]
jobs:
  readme-lies:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: sandeepsirodia/readme-lies@main
```

Findings show up as inline annotations on the PR diff.

## What it checks

| Claim in your docs | Checked against |
|---|---|
| `npm run X`, `pnpm run X`, `yarn run X`, `bun run X` | `scripts` in any `package.json` |
| `make X` / `just X` | targets in `Makefile` / recipes in `justfile` |
| `[link](path/to/file.md)`, images | the file exists (docs-site routes like `guide/x` → `guide/x.md` resolved) |
| `[link](#anchor)`, `[link](file.md#anchor)` | a heading with that anchor (GitHub, VitePress/Docusaurus, `{#custom-id}`, `<a name>`) |
| `` `src/some/file.ts` `` | the path exists |
| `` `someFunction()` `` | the name is still in the code. Only flagged if it *used* to be (via `git log -S`), so `useState()` and other third-party APIs never trigger |
| `yourtool --flag` | the flag appears in your tool's source (bins from `package.json` / `pyproject.toml`) |

## Built to not cry wolf

A linter that's wrong gets uninstalled. Every rule leans toward silence when it can't be sure:

- Scripts are only checked in root docs and contributor guides. `npm run build` in a tutorial usually means *the reader's* project, and so does anything after `npm init` / `npx create-…` / `mkdir`.
- `yarn husky`, `pnpm vitest`: without `run`, those are binaries, not scripts. Skipped.
- Gitignored targets (generated API docs) are skipped.
- Site-root routes in docs sites (`/guide/`), mkdocstrings pages, external URLs: skipped.
- Setext headings, emphasis in headings, CJK anchors, percent-encoding, mkdocs attr_list: handled.

Still wrong? Put `<!-- readme-lies-ignore -->` on the line above.

## Usage

```
readme-lies [paths…] [--root DIR] [--format text|github]
```

Exit code `1` if any lie is found, so it drops into any CI or pre-commit hook.

## Development

```bash
python -m unittest discover -s tests -v
```

Tests map to the expectations in [SPEC.md](SPEC.md). `TestNoFalsePositives` holds one regression test per false alarm ever seen in the wild. This README is checked by readme-lies in CI.

MIT © Sandeep Sirodia
