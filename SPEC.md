# readme-lies — SPEC

> Your README is lying. This catches it in CI.

A deterministic checker (no LLM in v1) that finds claims in Markdown docs that are no longer true of the code: commands that don't exist, files that moved, links to missing anchors, symbols that were renamed.

## Who it's for
Maintainers, and anyone whose README was last touched 8 months ago. It matters more now because coding agents read READMEs and trust them.

## Must have (v1)
1. **`readme-lies [paths…]`**: defaults to `README.md` and `docs/**/*.md`. Exit code 1 if any lie is found.
2. **Checks:**
   - **Script commands:** `npm run X` / `pnpm X` / `yarn X` → `X` exists in `package.json` scripts; `make X` → target exists; `just X` → recipe exists.
   - **Local paths** in links and inline code (`src/foo.ts`, `./docs/setup.md`) → file exists.
   - **Anchors:** `[x](#some-heading)` and `[x](file.md#heading)` → heading exists (GitHub slug rules).
   - **Symbols:** inline code like `` `createClient()` `` → a definition exists in the repo (grep for `function|def|class|const|export` patterns). Only flagged when a symbol previously existed in git history, to avoid noise.
   - **CLI flags:** `mytool --flag` where `mytool` is this repo's own bin → the flag appears in the source.
3. **Output:** `file:line: <claim> — <why it's false>`; `--format github` emits GitHub Actions annotations.
4. **GitHub Action** wrapper (`uses: you/readme-lies@v1`).
5. **Inline ignore:** `<!-- readme-lies-ignore -->` on the line above.

## Won't do (v1)
- LLM "semantic" drift (prose that describes behavior wrongly): v2 opt-in.
- External URL checking (lychee already does it well).
- Running the code blocks.

## Expectations → test cases
Fixtures: `tests/fixtures/<case>/` holds a mini repo with a README and an `expected.txt` listing the exact findings.

| ID | Given | When | Then |
|---|---|---|---|
| E1 | README says `npm run dev`; package.json has no `dev` script | Run | One finding at the correct line; exit 1 |
| E2 | README says `npm run build`; script exists | Run | No finding; exit 0 |
| E3 | Link to `./docs/setup.md` that was deleted | Run | Finding |
| E4 | Link `#installation` with heading `## Installation 🚀` | Run | No finding (GitHub slug rules handled) |
| E5 | Command inside a fenced block marked `console` with a `$ ` prompt | Run | Command parsed without the prompt, then checked |
| E6 | `` `oldName()` `` in the README; `oldName` existed in git history, was renamed | Run | Finding says "renamed/removed" |
| E7 | `` `useState()` `` (a third-party symbol never defined in the repo) | Run | No finding (no false positive on external APIs) |
| E8 | Line preceded by `<!-- readme-lies-ignore -->` | Run | That line is skipped |
| E9 | `--format github` | Run | Output lines match the `::error file=…,line=…::` format |
| E10 | Top 20 popular OSS repos (snapshot, run nightly) | Run | Every finding is hand-verified true. Track the false-positive rate; target 0 |
| E11 | readme-lies' own repo | Run in CI | Passes (dogfood) |

## Done when
- E1–E11 pass. README headline: "Found N lies in the READMEs of X popular repos". Open a few real PRs fixing them; that's the launch story.
