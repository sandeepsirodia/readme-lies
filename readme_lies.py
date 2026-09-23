"""readme-lies: your README is lying. This catches it in CI.

Deterministic checks (no LLM): npm/pnpm/yarn/bun scripts, make/just targets, local links,
anchors, file paths in inline code, symbols that were renamed away, and CLI flags of this
repo's own tools.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
from urllib.parse import unquote

__version__ = "0.1.0"

IGNORE = "<!-- readme-lies-ignore -->"
SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", ".venv", "venv", "__pycache__",
             "target", ".next", "coverage", ".tox", "site-packages"}
SOURCE_EXTS = (".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb", ".java",
               ".kt", ".swift", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".php", ".sh", ".lua",
               ".ex", ".exs", ".scala", ".dart", ".vue", ".svelte", ".zig", ".toml", ".json", ".yml", ".yaml",
               ".bash", ".zsh", ".fish", ".ps1", ".vim", ".el", ".hs", ".ml", ".clj", ".erl", ".nim", ".jl",
               ".pl", ".r", ".tf", ".nix", ".m")
SHELL_LANGS = {"", "bash", "sh", "shell", "zsh", "console", "shell-session", "terminal"}
# npm lifecycle scripts that exist implicitly
NPM_IMPLICIT = {"test", "start", "install", "restart", "stop"}

RE_FENCE = re.compile(r"^\s*(```+|~~~+)\s*([\w+-]*)")
RE_LINK = re.compile(r"!?\[(?:[^\]\\]|\\.)*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
RE_INLINE = re.compile(r"(`+)(.+?)\1")
# Only an explicit `run` is checked: `yarn husky` / `pnpm vitest` run binaries, not scripts.
RE_PM = re.compile(r"(?:^|[\s;&|(])(npm|pnpm|yarn|bun)\s+run(?:-script)?\s+(?:--\S+\s+)*([\w:.@/-]+)")
RE_SCAFFOLD = re.compile(r"\b(?:(?:npm|pnpm|yarn|bun)\s+(?:init|create)\s+\S|npx\s+create-|mkdir\s)")
RE_HEADING = re.compile(r"^#{1,6}\s")
RE_MAKE = re.compile(r"(?:^|[\s;&|(])(make|just)\s+((?:[\w.-]+\s*)+)")
RE_CODE_SPAN = re.compile(r"(`+).+?\1")
RE_SYMBOL = re.compile(r"^(?:[A-Za-z_$][\w$]*\.)*([A-Za-z_$][\w$]*)\(\)$")
RE_FLAG = re.compile(r"(?<![\w-])(--[a-z][\w-]*)")


class Finding:
    def __init__(self, file, line, claim, reason):
        self.file, self.line, self.claim, self.reason = file, line, claim, reason

    def text(self):
        return "%s:%d: %s — %s" % (self.file, self.line, self.claim, self.reason)

    def github(self):
        return "::error file=%s,line=%d::readme-lies: %s — %s" % (self.file, self.line, self.claim, self.reason)


# ------------------------------------------------------------------ repo facts

class Repo:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self._source = None
        self._history, self._grep, self._ignored = {}, {}, {}
        self.is_git = os.path.isdir(os.path.join(self.root, ".git"))
        self.scripts = self._npm_scripts()
        self.make_targets = self._targets("Makefile", r"^([A-Za-z0-9_.-]+)\s*:(?!=)")
        self.just_recipes = self._targets("justfile", r"^@?([A-Za-z0-9_-]+)[^:=\n]*:(?!=)")
        self.bins = self._bins()

    def walk(self, exts=None):
        for d, dirs, files in os.walk(self.root):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
            for f in files:
                if exts is None or f.endswith(exts):
                    yield os.path.join(d, f)

    def _npm_scripts(self):
        found = None
        for p in self.walk((".json",)):
            if os.path.basename(p) != "package.json":
                continue
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            found = (found or set()) | set((data.get("scripts") or {}).keys())
        return found  # None = no package.json, so we can't judge

    def _targets(self, name, pattern):
        for cand in (name, name.lower(), name.capitalize(), "GNUmakefile" if name == "Makefile" else ".justfile"):
            p = os.path.join(self.root, cand)
            if os.path.isfile(p):
                with open(p, encoding="utf-8", errors="replace") as f:
                    return set(re.findall(pattern, f.read(), re.M))
        return None

    def _bins(self):
        bins = set()
        pj = os.path.join(self.root, "package.json")
        if os.path.isfile(pj):
            try:
                with open(pj, encoding="utf-8") as f:
                    data = json.load(f)
                b = data.get("bin")
                if isinstance(b, dict):
                    bins |= set(b)
                elif isinstance(b, str) and data.get("name"):
                    bins.add(data["name"].split("/")[-1])
            except (OSError, ValueError):
                pass
        pp = os.path.join(self.root, "pyproject.toml")
        if os.path.isfile(pp):
            with open(pp, encoding="utf-8") as f:
                m = re.search(r"^\[project\.scripts\]\s*\n((?:[^\[\n].*\n?)*)", f.read(), re.M)
            if m:
                bins |= set(re.findall(r"^\s*\"?([\w.-]+)\"?\s*=", m.group(1), re.M))
        return bins

    @property
    def source(self):
        if self._source is None:
            chunks = []
            for p in self.walk(SOURCE_EXTS):
                try:
                    with open(p, encoding="utf-8", errors="replace") as f:
                        chunks.append(f.read())
                except OSError:
                    pass
            self._source = "\n".join(chunks)
        return self._source

    def _git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, timeout=60)

    def in_code(self, pattern, word=True):
        """Is `pattern` (fixed string) anywhere in the code, i.e. any tracked non-Markdown file?"""
        key = (pattern, word)
        if key not in self._grep:
            if self.is_git:
                try:
                    r = self._git("grep", "-q", "-I", "-F", *(["-w"] if word else []), "-e", pattern,
                                  "--", ".", ":(exclude)*.md", ":(exclude)*.markdown")
                    self._grep[key] = r.returncode == 0
                    return self._grep[key]
                except (OSError, subprocess.SubprocessError):
                    pass
            rx = r"\b%s\b" % re.escape(pattern) if word else re.escape(pattern)
            self._grep[key] = re.search(rx, self.source) is not None
        return self._grep[key]

    def ignored(self, path):
        """Gitignored targets are generated at build time (e.g. API reference docs): not a lie."""
        if not self.is_git:
            return False
        if path not in self._ignored:
            try:
                self._ignored[path] = self._git("check-ignore", "-q", path).returncode == 0
            except (OSError, subprocess.SubprocessError):
                self._ignored[path] = False
        return self._ignored[path]

    def in_history(self, word):
        """True if `word` ever appeared, as a whole word, in non-Markdown files in git history.
        `git log -S` matches substrings (`_fzf_x` contains `fzf_x`), so confirm in the patches."""
        if word not in self._history:
            try:
                out = self._git("log", "--all", "-S", word, "-n", "20", "-p", "--format=", "--",
                                ".", ":(exclude)*.md", ":(exclude)*.markdown")
                rx = re.compile(r"^[+-].*(?<![\w$])%s(?![\w$])" % re.escape(word), re.M)
                self._history[word] = rx.search(out.stdout) is not None
            except (OSError, subprocess.SubprocessError):
                self._history[word] = False
        return self._history[word]


# ------------------------------------------------------------------ markdown

def rendered(heading):
    """Heading text as rendered: no HTML, link targets, code ticks, or *emphasis* markers."""
    s = re.sub(r"<[^>]+>", "", heading)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    # strip *emphasis* only outside code spans: `__dunder__` keeps its underscores
    parts = re.split(r"(`+[^`]*`+)", s)
    s = "".join(p if p.startswith("`") else re.sub(r"(?<!\w)([*_]{1,3})(\S(?:.*?\S)?)\1(?!\w)", r"\2", p)
                for p in parts)
    return s.replace("`", "").strip().lower()


def slug_variants(heading):
    """Anchors a link author might expect: GitHub, a GitHub-like variant that keeps non-ASCII
    punctuation (CJK docs), and VitePress/Docusaurus (runs of non-word chars become '-')."""
    t = rendered(heading)
    return (
        re.sub(r"[^\w\- ]", "", t).replace(" ", "-"),
        re.sub(r"[!-,./:-@\[-^`{-~]", "", t).replace(" ", "-"),
        re.sub(r"[^\w]+", "-", t).strip("-"),
    )


def slugify(heading, seen):
    s = slug_variants(heading)[0]
    n = seen.get(s, 0)
    seen[s] = n + 1
    return s if n == 0 else "%s-%d" % (s, n)


def anchors_of(text):
    seen, out, in_fence, prev = {}, set(), False, ""
    for line in text.splitlines():
        if RE_FENCE.match(line):
            in_fence, prev = not in_fence, ""
            continue
        if in_fence:
            continue
        m = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m:
            h = m.group(1)
            custom = re.search(r"\s*\{#([\w-]+)\}\s*$", h)  # VitePress / mkdocs / Docusaurus {#id}
            if custom:
                out.add(custom.group(1))
                h = h[:custom.start()]
            out.add(slugify(h, seen))
            out.update(slug_variants(h))
        elif prev.strip() and re.match(r"^(=+|-+)\s*$", line) and not prev.lstrip().startswith(("-", "*", ">", "|")):
            out.add(slugify(prev.strip(), seen))  # setext heading
        prev = line
    out |= set(re.findall(r"""<\w+\s+[^>]*\b(?:name|id)=["']([^"']+)["']""", text))
    out |= set(re.findall(r"\{:?\s*#([\w.:-]+)[^}]*\}", text))  # mkdocs attr_list: {#id}, [](){#id}
    if re.search(r"^:::\s+\S", text, re.M):
        out.add("*")  # mkdocstrings page: anchors are generated from code, can't check
    return out


def parse(text):
    """Yield (line_no, kind, content): kind is 'prose' or 'cmd'. Ignored lines are dropped."""
    fence, lang, skip_next = None, "", False
    for i, line in enumerate(text.splitlines(), 1):
        if IGNORE in line:
            skip_next = True
            continue
        m = RE_FENCE.match(line)
        if m and (fence is None or m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)):
            if fence is None:
                fence, lang = m.group(1), m.group(2).lower()
            else:
                fence = None
            skip_next = False
            continue
        if skip_next:
            skip_next = False
            continue
        if fence is None:
            yield i, "heading" if RE_HEADING.match(line) else "prose", line
        elif lang in SHELL_LANGS:
            s = line.strip()
            if lang in ("console", "shell-session", "terminal") or s.startswith("$ "):
                if not s.startswith("$ "):
                    continue  # command output, not a command
                s = s[2:]
            if s and not s.startswith("#"):
                yield i, "cmd", s


# ------------------------------------------------------------------ checks

def check_commands(repo, cmd, line, rel, out, scripts=True):
    for m in RE_PM.finditer(cmd):
        pm, name = m.group(1), m.group(2)
        if not scripts or repo.scripts is None or name.startswith("-"):
            continue
        if pm == "npm" and name in NPM_IMPLICIT:
            continue
        if name not in repo.scripts:
            out.append(Finding(rel, line, "`%s`" % m.group(0).strip(), "no \"%s\" script in package.json" % name))
    for m in RE_MAKE.finditer(cmd):
        tool, targets = m.group(1), repo.make_targets if m.group(1) == "make" else repo.just_recipes
        if targets is None:
            continue
        for t in m.group(2).split():
            if t.startswith("-") or "=" in t:
                break
            if t not in targets:
                out.append(Finding(rel, line, "`%s %s`" % (tool, t),
                                   "no \"%s\" target in %s" % (t, "Makefile" if tool == "make" else "justfile")))
    for b in repo.bins:
        for m in re.finditer(r"(?:^|[\s;&|(])%s((?:\s+\S+)*)" % re.escape(b), cmd):
            args = re.sub(r"'[^']*'|\"[^\"]*\"", " ", m.group(1))  # flags inside quotes belong to other programs. teeth: ignore — group(0) only adds the tool name; equivalent
            for flag in RE_FLAG.findall(args):
                if flag in ("--help", "--version"):
                    continue
                bare = flag[2:]
                if not repo.in_code(flag, word=False) and not repo.in_code('"%s"' % bare, word=False) \
                        and not repo.in_code("'%s'" % bare, word=False):
                    out.append(Finding(rel, line, "`%s %s`" % (b, flag), "flag not found in %s's source" % b))


def looks_like_path(s):
    return ("/" in s and " " not in s and "://" not in s and not s.startswith(("/", "~", "$", "-", "@"))
            and not re.search(r"[*?{}<>|=:,()\[\]]", s) and re.search(r"\.\w{1,6}$|/$", s) is not None)


def resolve(*bases):
    """Docs-site style links: `guide/x` -> guide/x.md, guide/x/index.md, x.html -> x.md."""
    for full in bases:
        cands = [full, full + ".md", os.path.join(full, "index.md"), os.path.join(full, "README.md")]
        if full.endswith(".html"):
            cands.append(full[:-5] + ".md")
        found = next((c for c in cands if os.path.exists(c)), None)
        if found:
            return found
    return None


def has_anchor(anchors, frag):
    return "*" in anchors or frag in anchors or frag.lower() in anchors


def check_prose(repo, md_path, text_line, line, rel, anchors, out, scripts=True):
    md_dir = os.path.dirname(md_path)
    is_root_doc = os.path.dirname(md_path) == repo.root
    for m in RE_LINK.finditer(RE_CODE_SPAN.sub("", text_line)):
        target = unquote(m.group(1)).replace("`", "")
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("//"):
            continue
        path, _, frag = target.partition("#")
        if not path:
            if frag and not has_anchor(anchors(md_path), frag):
                out.append(Finding(rel, line, "[…](#%s)" % frag, "no heading with that anchor"))
            continue
        if path.startswith("/") and not is_root_doc:
            continue  # site-root route of a docs framework (VitePress, Docusaurus…): unknowable
        path = path.split("?")[0]
        full = os.path.normpath(os.path.join(repo.root if path.startswith("/") else md_dir, path.lstrip("/")))
        bases = [full]
        if not is_root_doc and not path.startswith("/") and not os.path.splitext(path)[1]:
            # mkdocs directory URLs: docs/async.md is served at /async/, so links resolve from there
            bases.append(os.path.normpath(os.path.join(os.path.splitext(md_path)[0], path)))
        found = resolve(*bases)
        if found is None:
            if not repo.ignored(full):
                out.append(Finding(rel, line, "[…](%s)" % target, "file does not exist"))
        elif frag and found.endswith((".md", ".markdown")) and not has_anchor(anchors(found), frag):
            out.append(Finding(rel, line, "[…](%s)" % target, "no heading with that anchor in %s" % path))
    stripped = RE_LINK.sub("", text_line)
    for m in RE_INLINE.finditer(stripped):
        code = m.group(2).strip()
        if looks_like_path(code):
            first = code.lstrip("./").split("/")[0]
            if os.path.isdir(os.path.join(repo.root, first)):  # `./pyproject.toml` may mean the reader's project
                # inline paths are usually relative to the repo root (where you run commands), sometimes to the doc
                cands = [os.path.normpath(os.path.join(b, code)) for b in (repo.root, md_dir)]
                if not any(os.path.exists(c) for c in cands) and not repo.ignored(cands[0]):
                    out.append(Finding(rel, line, "`%s`" % code, "path does not exist"))
            continue
        sym = RE_SYMBOL.match(code)
        if sym:
            name = sym.group(1)
            if len(name) >= 3 and not repo.in_code(name) and repo.in_history(name):
                out.append(Finding(rel, line, "`%s`" % code, "`%s` is not in the code (renamed or removed?)" % name))
            continue
        if code.startswith(("npm ", "pnpm ", "yarn ", "bun ", "make ", "just ")) or any(
                code == b or code.startswith(b + " ") for b in repo.bins):
            check_commands(repo, code, line, rel, out, scripts)


def check_file(repo, md_path, anchor_cache):
    def anchors(p):
        if p not in anchor_cache:
            try:
                with open(p, encoding="utf-8") as f:
                    anchor_cache[p] = anchors_of(f.read())
            except OSError:
                anchor_cache[p] = set()
        return anchor_cache[p]

    rel = os.path.relpath(md_path, repo.root)
    with open(md_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    out = []
    # Scripts are checked in root docs and contributor guides. Elsewhere `npm run build` usually means
    # the reader's project, and so does any doc that shows a "scripts" block.
    name = os.path.basename(md_path).lower()
    about_this_repo = os.path.dirname(md_path) == repo.root or "contribut" in name or "develop" in name
    teaches_scripts = '"scripts"' in text or not about_this_repo
    scaffold = False  # after `npm init x` / `mkdir app`, commands refer to the reader's new project
    for line, kind, content in parse(text):
        if kind == "heading":
            scaffold = False
        if RE_SCAFFOLD.search(content):
            scaffold = True
        scripts = not teaches_scripts and not scaffold
        if kind == "cmd":
            check_commands(repo, content, line, rel, out, scripts)
        else:
            check_prose(repo, md_path, content, line, rel, anchors, out, scripts)
    return out


def default_docs(root):
    found = [p for p in ("README.md", "readme.md", "Readme.md") if os.path.isfile(os.path.join(root, p))][:1]
    found += sorted(glob.glob(os.path.join(root, "docs", "**", "*.md"), recursive=True))
    return [os.path.join(root, p) if not os.path.isabs(p) else p for p in found]


def run(root=".", paths=None):
    repo = Repo(root)
    files = [os.path.abspath(p) for p in paths] if paths else default_docs(repo.root)
    cache, findings, seen = {}, [], set()
    for p in files:
        for f in check_file(repo, p, cache):
            if (f.file, f.line, f.claim) not in seen:
                seen.add((f.file, f.line, f.claim))
                findings.append(f)
    return findings


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(prog="readme-lies", description="Find claims in your docs that the code no longer backs up.")
    ap.add_argument("paths", nargs="*", help="Markdown files (default: README.md + docs/**/*.md)")
    ap.add_argument("--root", default=".", help="repository root (default: .)")
    ap.add_argument("--format", choices=["text", "github"], default="text")
    ap.add_argument("--version", action="version", version=__version__)
    a = ap.parse_args(argv)
    findings = run(a.root, a.paths)
    for f in findings:
        out.write((f.github() if a.format == "github" else f.text()) + "\n")
    if a.format == "text":
        out.write("%s\n" % ("%d lie(s) found." % len(findings) if findings else "No lies found. Your README is honest."))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
