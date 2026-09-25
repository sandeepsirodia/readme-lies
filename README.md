<h1 align="center">readme-lies</h1>

<p align="center">
  <em>Your README is lying. Your agent believes it.</em>
</p>

<p align="center">
  <a href="https://github.com/sandeepsirodia/readme-lies/actions/workflows/ci.yml"><img src="https://github.com/sandeepsirodia/readme-lies/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/dependencies-0-111111?style=flat-square" alt="Zero dependencies">
  <img src="https://img.shields.io/badge/LLM-none-111111?style=flat-square" alt="No LLM">
  <img src="https://img.shields.io/badge/license-MIT-111111?style=flat-square" alt="MIT">
</p>

<p align="center">
  <strong>11 real doc bugs found in httpx, pydantic, uv &amp; typer · 83% precision on repos it had never seen</strong>
</p>

---

You clone a repo. The README says:

```bash
npm run dev
```

There is no `dev` script. There hasn't been for eight months. Someone renamed it to `start` and never touched the docs.

You shrug and go look at `package.json`. **Your coding agent doesn't shrug.** It runs the command, reads the error, guesses, tries three variations, and burns ten minutes of your tokens, because the README said so.

Docs don't rot loudly. They rot one renamed heading at a time. **readme-lies checks every claim your docs make against the code, on every push.**

## What it catches

```console
$ readme-lies
README.md:42: `npm run dev` — no "dev" script in package.json
README.md:77: […](docs/setup.md) — file does not exist
docs/api.md:12: […](#client-instances) — no heading with that anchor
docs/api.md:30: `createClient()` — `createClient` is not in the code (renamed or removed?)
4 lie(s) found.
```

| Your docs say… | readme-lies checks… |
|---|---|
| `npm run build` · `pnpm run test` · `make deploy` · `just lint` | that script / target / recipe actually exists |
| `[see setup](docs/setup.md)` | that the file is still there |
| `[config](#configuration)` | that the heading still exists: GitHub, VitePress, Docusaurus and mkdocs rules |
| `` `src/server/auth.ts` `` | that the path is real |
| `` `createClient()` `` | that the function wasn't renamed away. Only flagged if it *used to exist*, so `useState()` never trips it |
| `mytool --verbose` | that your CLI still has that flag |

## It already found real bugs

<p align="center"><img src="https://raw.githubusercontent.com/sandeepsirodia/readme-lies/main/assets/httpx.svg" alt="readme-lies on encode/httpx: 7 links to headings that no longer exist" width="820"></p>

I pointed it at 27 popular repositories and checked every finding by hand. These are live on `main` as I write this:

| Repo | Lies | Example |
|---|---|---|
| encode/httpx | 7 | links to `#client-instances`, `#routing`, `#http-proxying`: all headings that got renamed |
| fastapi/typer | 2 | the root README links `tutorial/install.md`, which lives in `docs/`, so it's a 404 on GitHub |
| astral-sh/uv | 1 | `init.md#unpackaged-applications`: no such section |
| pydantic/pydantic | 1 | `#customise-settings-sources` on a page that's now a stub |

On 12 repos it had **never seen** during development, 10 of its 12 findings were real (83%). The other two taught it something, and every false alarm it has ever raised is now a regression test.

## Add it to CI (30 seconds)

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

Lies show up as red annotations right on the PR diff, the moment someone renames the thing the docs point to.

Or just run it:

```bash
uvx --from git+https://github.com/sandeepsirodia/readme-lies readme-lies
```

## Built to not cry wolf

A linter that's wrong twice gets uninstalled. So every rule stays quiet unless it's sure:

- `npm run build` inside a tutorial usually means *the reader's* project, not yours, so scripts are only checked in root docs and contributor guides. The same goes for anything after `npm init`, `npx create-…` or `mkdir`.
- `yarn husky` runs a binary, not a script. It's skipped.
- Gitignored files (generated API docs) are skipped.
- Docs-site routes like `/guide/` and mkdocstrings pages are skipped.
- Setext headings, `_emphasis_` in headings, CJK anchors, percent-encoding and `{#custom-ids}`: handled.

Still wrong? Put `<!-- readme-lies-ignore -->` on the line above and it'll look away.

<details>
<summary><b>Usage &amp; development</b></summary>

```
readme-lies [paths…] [--root DIR] [--format text|github]
```

Defaults to `README.md` plus `docs/**/*.md`. Exits `1` when it finds a lie, so it drops into any CI or pre-commit hook. One Python file, zero dependencies, no LLM, no network.

```bash
python -m unittest discover -s tests -v
```

Tests map to [SPEC.md](SPEC.md). `TestNoFalsePositives` holds one regression test per false alarm ever seen in the wild. And yes: this README is checked by readme-lies on every push.

</details>

## Prior art, and what's new here

- **[lychee](https://github.com/lycheeverse/lychee)** checks URLs (readme-lies deliberately doesn't).
- **[markdown-link-check](https://github.com/tcort/markdown-link-check)** and **[remark-validate-links](https://github.com/remarkjs/remark-validate-links)** check local links and headings. If that's all you need, they're mature choices.

readme-lies goes past links, to the **claims** docs make about the code:
- package scripts and make/just targets
- file paths in inline code
- functions that were renamed away (via git history)
- your CLI's own flags

It also handles the anchor rules of docs sites (VitePress, Docusaurus, mkdocs), not just GitHub's.

<p align="center"><sub>MIT © Sandeep Sirodia · Found a lie in your own README? A ⭐ is a nice way to say thanks.</sub></p>
