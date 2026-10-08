"""Write paper.rendered.md: paper.md with its pandoc citations rendered for reading on Forgejo.

paper.md cites references.bib with pandoc keys ([@key], @key). Forgejo shows those raw, so this
renders every citation through pandoc's citeproc (the same Chicago author–date style as the PDF),
substitutes the rendered text into an otherwise untouched copy of paper.md, and fills the
`::: {#refs}` block with the reference list.

    uv run python tools/render_md.py
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIB = ROOT / "references.bib"
KEY = r"[A-Za-z][A-Za-z0-9_]*"
BRACKET = re.compile(r"\[(?:[^\[\]]*?)(?<![\\\w])-?@" + KEY + r"[^\[\]]*\]")
NARRATIVE = re.compile(r"(?<![\\\w@\[])@(" + KEY + r")")
SEP = "QQSEPQQ"


def pandoc(text: str, to: str) -> str:
    out = subprocess.run(["pandoc", "--citeproc", "--bibliography", str(BIB), "-f", "markdown", "-t", to, "--wrap=none"],
                         input=text.encode(), capture_output=True, check=True)
    return out.stdout.decode()


def main() -> None:
    src = (ROOT / "paper.md").read_text()
    head, sep, tail = src.partition("::: {#refs}\n:::")
    groups = sorted(set(BRACKET.findall(src)))
    rendered = {}
    if groups:
        doc = f"\n\n{SEP}\n\n".join(groups) + "\n\n::: {#refs}\n:::\n"
        parts = pandoc(doc, "plain").split(SEP)
        for g, r in zip(groups, parts):
            rendered[g] = r.strip().split("\n\n")[0].strip()
    def sub_text(t: str) -> str:
        for g in sorted(rendered, key=len, reverse=True):
            t = t.replace(g, rendered[g])
        keys = sorted(set(NARRATIVE.findall(t)))
        if keys:
            doc = f"\n\n{SEP}\n\n".join("@" + k for k in keys) + "\n\n::: {#refs}\n:::\n"
            parts = pandoc(doc, "plain").split(SEP)
            for k, r in zip(keys, parts):
                t = re.sub(r"(?<![\\\w@\[])@" + re.escape(k) + r"(?!\w)", r.strip().split("\n\n")[0].strip(), t)
        return t
    refs = ""
    if sep:
        refs = pandoc("---\nnocite: '@*'\n---\n\n::: {#refs}\n:::\n", "gfm")
        refs = re.sub(r"<div[^>]*>|</div>", "", refs)
        refs = re.sub(r'<span class="nocase">(.*?)</span>', r"\1", refs)
        refs = re.sub(r"\n{3,}", "\n\n", refs).strip() + "\n"
    out = sub_text(head) + refs + (sub_text(tail) if sep else "")
    note = "<!-- Generated from paper.md by tools/render_md.py; edit paper.md, not this file. -->\n\n"
    (ROOT / "paper.rendered.md").write_text(note + out)
    print("wrote paper.rendered.md:", len(rendered), "bracketed citation groups")


if __name__ == "__main__":
    main()
