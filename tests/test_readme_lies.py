"""Tests map 1:1 to SPEC.md expectations (E1..E11)."""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import readme_lies as rl  # noqa: E402


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                   cwd=cwd, check=True, capture_output=True)


class Repo:
    def __init__(self, files):
        self.root = tempfile.mkdtemp()
        for path, content in files.items():
            self.write(path, content)

    def write(self, path, content):
        p = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(content) if isinstance(content, str) else json.dumps(content))

    def lies(self, *paths):
        return rl.run(self.root, [os.path.join(self.root, p) for p in paths] or None)

    def cli(self, *argv):
        out = io.StringIO()
        code = rl.main(["--root", self.root, *argv], out=out)
        return code, out.getvalue()


PKG = {"name": "demo", "scripts": {"build": "tsc", "lint": "eslint ."}}


class TestSpec(unittest.TestCase):
    def test_e1_missing_npm_script(self):
        r = Repo({"package.json": PKG, "README.md": "# Demo\n\nStart it:\n\n```bash\nnpm run dev\n```\n"})
        found = r.lies()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].line, 6)
        self.assertIn('no "dev" script', found[0].reason)
        self.assertEqual(r.cli()[0], 1)

    def test_e2_existing_script_is_fine(self):
        r = Repo({"package.json": PKG, "README.md": "Run `npm run build` then `pnpm lint` and `yarn install`.\n"})
        self.assertEqual(r.lies(), [])
        self.assertEqual(r.cli()[0], 0)

    def test_e3_deleted_linked_file(self):
        r = Repo({"README.md": "See [setup](./docs/setup.md) and [usage](docs/usage.md).\n", "docs/usage.md": "# Usage\n"})
        found = r.lies("README.md")
        self.assertEqual([f.claim for f in found], ["[…](./docs/setup.md)"])

    def test_e4_github_slug_rules(self):
        r = Repo({"README.md": """\
            # Project
            - [Install](#installation-)
            - [API](#api-reference)
            - [Dup](#usage-1)
            - [Missing](#nope)

            ## Installation 🚀
            ## API `Reference`
            ## Usage
            ## Usage
            """})
        found = r.lies()
        self.assertEqual([f.claim for f in found], ["[…](#nope)"])

    def test_e5_console_prompt_and_output(self):
        r = Repo({"package.json": PKG, "README.md": """\
            ```console
            $ npm run build
            > demo@1.0.0 build
            npm run this-is-output-not-a-command
            $ npm run deploy
            ```
            """})
        found = r.lies()
        self.assertEqual([f.claim for f in found], ["`npm run deploy`"])
        self.assertEqual(found[0].line, 5)

    def test_e6_renamed_symbol(self):
        r = Repo({"src/client.js": "export function oldName() {}\n", "README.md": "Call `oldName()` to start.\n"})
        git(r.root, "init", "-q")
        git(r.root, "add", ".")
        git(r.root, "commit", "-qm", "init")
        r.write("src/client.js", "export function createClient() {}\n")
        git(r.root, "commit", "-qam", "rename")
        found = r.lies()
        self.assertEqual(len(found), 1)
        self.assertIn("renamed or removed", found[0].reason)

    def test_e7_external_symbol_not_flagged(self):
        r = Repo({"src/app.js": "import x from 'y'\n", "README.md": "Works with `useState()` and `React.useEffect()`.\n"})
        git(r.root, "init", "-q")
        git(r.root, "add", ".")
        git(r.root, "commit", "-qm", "init")
        self.assertEqual(r.lies(), [])

    def test_e8_ignore_comment(self):
        r = Repo({"package.json": PKG, "README.md": "<!-- readme-lies-ignore -->\n`npm run dev`\n`npm run nope`\n"})
        self.assertEqual([f.line for f in r.lies()], [3])

    def test_e9_github_format(self):
        r = Repo({"package.json": PKG, "README.md": "`npm run dev`\n"})
        code, out = r.cli("--format", "github")
        self.assertEqual(code, 1)
        self.assertRegex(out.strip(), r"^::error file=README\.md,line=1::readme-lies: .+")

    def test_e11_dogfood(self):
        found = rl.run(ROOT)
        self.assertEqual(found, [], "\n".join(f.text() for f in found))


class TestCoverage(unittest.TestCase):
    def test_make_and_just_targets(self):
        r = Repo({"Makefile": "build:\n\tgo build\nVAR := 1\n", "justfile": "test *args:\n  go test\n",
                  "README.md": "```sh\nmake build\nmake release\njust test\njust deploy\n```\n"})
        self.assertEqual(sorted(f.claim for f in r.lies()), ["`just deploy`", "`make release`"])

    def test_inline_paths(self):
        r = Repo({"src/a.py": "", "README.md": "Edit `src/a.py` or `src/b.py`. Output goes to `dist/app.js`.\n"})
        self.assertEqual([f.claim for f in r.lies()], ["`src/b.py`"])

    def test_cross_file_anchor(self):
        r = Repo({"docs/api.md": "# API\n## Auth\n", "README.md": "[a](docs/api.md#auth) [b](docs/api.md#billing)\n"})
        self.assertEqual([f.claim for f in r.lies()], ["[…](docs/api.md#billing)"])

    def test_cli_flags_of_own_bin(self):
        r = Repo({"pyproject.toml": '[project]\nname = "tool"\n\n[project.scripts]\nmytool = "tool:main"\n',
                  "tool.py": "p.add_argument('--verbose')\n",
                  "README.md": "```bash\nmytool --verbose --dry-run\nothertool --whatever\n```\n"})
        self.assertEqual([f.claim for f in r.lies()], ["`mytool --dry-run`"])

    def test_no_package_json_no_judgement(self):
        r = Repo({"README.md": "`npm run anything`\n"})
        self.assertEqual(r.lies(), [])

    def test_urls_and_mailto_skipped(self):
        r = Repo({"README.md": "[x](https://example.com/missing.md) [m](mailto:a@b.c)\n"})
        self.assertEqual(r.lies(), [])


class TestNoFalsePositives(unittest.TestCase):
    """Regressions from E10 (running on 15 popular repos). Each case was a real false alarm."""

    def test_setext_headings(self):  # fzf
        self.assertEqual(Repo({"README.md": "[i](#installation)\n\nInstallation\n------------\n"}).lies(), [])

    def test_anchor_on_any_tag(self):  # ripgrep FAQ: <h3 name="complete">
        r = Repo({"FAQ.md": '<h3 name="complete">\nQ?\n</h3>\n', "README.md": "[q](FAQ.md#complete)\n"})
        self.assertEqual(r.lies(), [])

    def test_slug_keeps_underscores(self):  # commander: ### cmd._args -> #cmd_args
        self.assertEqual(Repo({"README.md": "[a](#cmd_args)\n\n### cmd._args\n"}).lies(), [])

    def test_percent_encoded_links(self):  # commander zh-CN
        r = Repo({"README.md": "[x](#%E4%B8%AD%E6%96%87) [y](./%E6%96%87.md)\n\n## 中文\n", "文.md": "hi\n"})
        self.assertEqual(r.lies(), [])

    def test_link_syntax_inside_code_span(self):  # fastify style guide
        self.assertEqual(Repo({"README.md": "Write links as `[Title](www.site.com)`.\n"}).lies(), [])

    def test_gitignored_generated_docs(self):  # uv: docs/reference/*.md generated at build
        r = Repo({".gitignore": "/docs/reference/\n", "docs/guide.md": "[s](../docs/reference/settings.md#x)\n",
                  "README.md": "x\n"})
        git(r.root, "init", "-q")
        self.assertEqual(r.lies(), [])

    def test_docs_site_routes(self):  # vite / axios / prettier: VitePress-style routes
        r = Repo({"README.md": "x\n", "docs/guide/features.md": "# F\n",
                  "docs/index.md": "[a](/team) [b](/images/x.png) [c](./guide/features) [d](guide/features.html)\n"})
        self.assertEqual(r.lies(), [])

    def test_scaffolded_project_scripts(self):  # fastify README: npm init fastify -> npm run dev
        r = Repo({"package.json": PKG, "README.md": "## Quick start\n```sh\nnpm init fastify\n```\n```sh\nnpm run dev\n```\n"
                  "## Contributing\n```sh\nnpm run nope\n```\n"})
        self.assertEqual([f.claim for f in r.lies()], ["`npm run nope`"])

    def test_doc_teaching_scripts(self):  # fastify TypeScript guide
        r = Repo({"package.json": PKG, "README.md": 'Add `"scripts": {"dev": "x"}` then run `npm run dev`.\n'})
        self.assertEqual(r.lies(), [])

    def test_package_binaries_not_scripts(self):  # prettier: `yarn husky`
        self.assertEqual(Repo({"package.json": PKG, "README.md": "`yarn husky` `pnpm vitest` `bun x`\n"}).lies(), [])

    def test_docs_site_anchor_rules(self):  # vite: `## build.target` -> #build-target; axios: d'une -> d-une
        r = Repo({"README.md": "[a](#build-target) [b](#d-une-instance) [c](#custom) [d](#方案一：让--成为)\n\n"
                               "## build.target\n## D'une instance\n## Anything {#custom}\n## 方案一：让`--`成为\n"})
        self.assertEqual(r.lies(), [])

    def test_emphasis_in_heading(self):  # commander: ### Declaring _program_ variable
        self.assertEqual(Repo({"README.md": "[a](#declaring-program-variable)\n\n### Declaring _program_ variable\n"}).lies(), [])

    def test_dot_slash_path_may_mean_readers_project(self):  # uv: `./pyproject.toml`
        self.assertEqual(Repo({"README.md": "Edit `./pyproject.toml`.\n"}).lies(), [])

    def test_flags_inside_quoted_args_belong_to_other_programs(self):  # lucky README: lucky './eval.sh --model a'
        r = Repo({"pyproject.toml": '[project]\nname = "t"\n\n[project.scripts]\nlucky = "t:main"\n',
                  "t.py": "p.add_argument('-n')\n",
                  "README.md": "```bash\nlucky -n 20 './eval.sh --model a' \"./b --fast\"\nlucky --nope\n```\n"})
        self.assertEqual([f.claim for f in r.lies()], ["`lucky --nope`"])

    def test_same_finding_reported_once(self):
        r = Repo({"package.json": PKG, "README.md": "`npm run dev` and again `npm run dev`\n"})
        self.assertEqual(len(r.lies()), 1)

    def test_dunder_in_code_span_heading(self):  # pydantic: ### Implementing `__get_schema__`
        self.assertEqual(Repo({"README.md": "[a](#implementing-__get_schema__)\n\n### Implementing `__get_schema__`\n"}).lies(), [])

    def test_mkdocs_attr_list_and_mkdocstrings(self):  # pydantic
        r = Repo({"README.md": "x\n", "docs/api.md": "::: pkg.config\n",
                  "docs/c.md": "[a](#plain) [b](#note) [c](api.md#pkg.config.X)\n\n### Plain\n  {#plain}\n\n[](){#note}\n"})
        self.assertEqual(r.lies(), [])

    def test_mkdocs_directory_urls(self):  # httpx: docs/async.md -> ../advanced/transports
        r = Repo({"README.md": "x\n", "docs/advanced/transports.md": "## ASGITransport\n",
                  "docs/async.md": "[t](../advanced/transports#asgitransport)\n"})
        self.assertEqual(r.lies(), [])

    def test_inline_dot_path_from_repo_root(self):  # typer: docs/contributing.md mentions `./scripts/docker/`
        r = Repo({"README.md": "x\n", "scripts/docker/run.sh": "", "docs/contributing.md": "Use `./scripts/docker/`.\n"})
        self.assertEqual(r.lies(), [])

    def test_scripts_in_user_facing_docs_skipped(self):  # execa docs/bash.md
        r = Repo({"package.json": PKG, "README.md": "x\n", "docs/bash.md": "`npm run build-app`\n",
                  "docs/contributing.md": "`npm run nope`\n"})
        self.assertEqual([f.file for f in r.lies()], ["docs/contributing.md"])

    def test_history_match_is_whole_word(self):  # `_fzf_x` in history must not count as `fzf_x` having existed
        r = Repo({"lib.sh": "_helper_path() {}\n", "README.md": "Call `helper_path()`.\n"})
        git(r.root, "init", "-q")
        git(r.root, "add", ".")
        git(r.root, "commit", "-qm", "init")
        self.assertEqual(r.lies(), [])

    def test_action_manifest_is_valid_yaml_shape(self):
        # no unquoted "key: value" inside a plain scalar (broke the Action once)
        for line in open(os.path.join(ROOT, "action.yml"), encoding="utf-8"):
            m = re.match(r"^\s*[\w-]+:\s+([^\"'].*)$", line)
            if m:
                self.assertNotRegex(m.group(1), r":\s", line)

    def test_symbol_defined_in_any_tracked_file(self):  # fzf: function lives in completion.zsh
        r = Repo({"shell/completion.zsh": "_fzf_compgen_path() {}\n", "README.md": "Override `_fzf_compgen_path()`.\n"})
        git(r.root, "init", "-q")
        git(r.root, "add", ".")
        git(r.root, "commit", "-qm", "init")
        self.assertEqual(r.lies(), [])


if __name__ == "__main__":
    unittest.main()
