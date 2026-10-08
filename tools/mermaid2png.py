"""Render the ```mermaid flowcharts in paper.md to PNG via Graphviz, for the PDF build.

Forgejo renders mermaid natively; pandoc does not. This translates the flowchart subset the paper
uses (nodes A[text], A[(text)], A{text}; edges A --> B and A -->|label| B) to dot and writes
figures/fig_mermaid_<sha1[:8]>.png (and a vector PDF in dist/fig/ for the preprint), which tools/math-block.lua substitutes for the block.

    uv run python tools/mermaid2png.py
"""
import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE = re.compile(r"(\w+)(\[\((.*?)\)\]|\[(.*?)\]|\{(.*?)\})?")
EDGE = re.compile(r"^\s*(.+?)\s*-->\s*(?:\|(.*?)\|\s*)?(.+?)\s*$")


def node(tok: str, nodes: dict) -> str:
    m = NODE.fullmatch(tok.strip())
    nid = m.group(1)
    if m.group(3) is not None:
        nodes[nid] = (m.group(3), "cylinder")
    elif m.group(4) is not None:
        nodes[nid] = (m.group(4), "box")
    elif m.group(5) is not None:
        nodes[nid] = (m.group(5), "diamond")
    else:
        nodes.setdefault(nid, (nid, "box"))
    return nid


def to_dot(src: str) -> str:
    nodes, edges = {}, []
    lines = src.strip().splitlines()
    rankdir = "LR" if "LR" in lines[0] else "TB"
    for ln in lines[1:]:
        m = EDGE.match(ln)
        if m:
            edges.append((node(m.group(1), nodes), node(m.group(3), nodes), m.group(2)))
    esc = lambda t: t.replace("<br/>", "\\n").replace('"', '\\"')
    out = [f'digraph G {{ rankdir={rankdir}; bgcolor="white"; nodesep=0.35; ranksep=0.5;',
           'node [fontname="Helvetica", fontsize=11, style="rounded", penwidth=1.2];',
           'edge [fontname="Helvetica", fontsize=9, color="#444444"];']
    for nid, (txt, shape) in nodes.items():
        style = ', style="filled", fillcolor="#f2f2f2"' if shape != "box" else ', style="rounded"'
        out.append(f'{nid} [label="{esc(txt)}", shape={shape}{style}];')
    for a, b, lab in edges:
        out.append(f'{a} -> {b}' + (f' [label="{esc(lab)}"]' if lab else "") + ";")
    return "\n".join(out + ["}"])


def main() -> None:
    text = (ROOT / "paper.md").read_text()
    for src in re.findall(r"```mermaid\n(.*?)```", text, re.S):
        h = hashlib.sha1(src.encode()).hexdigest()[:8]
        png = ROOT / "figures" / f"fig_mermaid_{h}.png"
        subprocess.run(["dot", "-Tpng", "-Gdpi=220", "-o", str(png)], input=to_dot(src).encode(), check=True)
        vec = ROOT / "dist" / "fig" / f"fig_mermaid_{h}.pdf"          # vector copy in the paper's serif for the preprint
        vec.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["dot", "-Tpdf", "-o", str(vec)], input=to_dot(src).replace("Helvetica", "STIX Two Text").encode(), check=True)
        print("wrote", png.name, "and", vec.name)


if __name__ == "__main__":
    main()
