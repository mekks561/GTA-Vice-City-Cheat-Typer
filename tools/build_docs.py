# -*- coding: utf-8 -*-
"""2.0-G：把 docs/*.md + README 生成离线静态站（零第三方依赖）。

用法：  python tools/build_docs.py
输出：  docs/site/*.html + docs/site/index.html

刻意只支持 Markdown 的一个小子集（标题/表格/代码块/列表/引用/行内格式），
够用即可；生成的 HTML 无外链、无 JS，双击即可离线打开。
"""

from __future__ import annotations

import html
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
SITE = os.path.join(DOCS, "site")

CSS = """
:root{--bg:#f7f8fa;--card:#fff;--text:#1a1f29;--muted:#6b7280;--line:#e3e7ee;--accent:#2563eb}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.7 "Microsoft YaHei UI",system-ui,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px}
header{background:var(--card);border-bottom:1px solid var(--line);padding:18px 0;margin-bottom:24px}
header .wrap{padding:0 24px}header h1{margin:0;font-size:20px}
nav a{display:inline-block;margin:8px 12px 0 0;color:var(--accent);text-decoration:none;font-size:14px}
nav a:hover{text-decoration:underline}
article{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:28px 34px}
h1,h2,h3,h4{line-height:1.35;margin:1.6em 0 .6em}h1{font-size:26px}h2{font-size:21px;
border-bottom:1px solid var(--line);padding-bottom:6px}h3{font-size:17px}
pre{background:#0f172a;color:#cbd5e1;padding:14px 16px;border-radius:8px;overflow:auto;font:13px/1.6 Consolas,monospace}
code{background:#eef2f7;padding:2px 5px;border-radius:4px;font:13px Consolas,monospace}
pre code{background:none;padding:0;color:inherit}
table{border-collapse:collapse;width:100%;margin:14px 0;font-size:14px}
th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{background:#eef1f6}blockquote{border-left:4px solid var(--accent);background:#f4f7ff;
margin:14px 0;padding:8px 16px;color:#374151}
ul,ol{padding-left:24px}a{color:var(--accent)}.foot{color:var(--muted);font-size:13px;margin-top:24px}
"""


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def render(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    in_code = False
    code_buf: list[str] = []
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
                code_buf = []
            in_code = not in_code
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue
        if not line.strip():
            i += 1
            continue
        if line.startswith("#"):
            m = re.match(r"^(#{1,6})\s+(.*)$", line)
            if m:
                lvl = len(m.group(1))
                out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
                i += 1
                continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|", lines[i + 1]):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head = rows[0]
            body = rows[2:] if len(rows) > 1 else []
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>")
            for r in body:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            out.append("</tbody></table>")
            continue
        if re.match(r"^\s*[-*+]\s+", line) or re.match(r"^\s*\d+\.\s+", line):
            ordered = bool(re.match(r"^\s*\d+\.\s+", line))
            tag = "ol" if ordered else "ul"
            items = []
            while i < len(lines) and (re.match(r"^\s*[-*+]\s+", lines[i]) or re.match(r"^\s*\d+\.\s+", lines[i])):
                items.append(re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", lines[i]))
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            continue
        if line.lstrip().startswith(">"):
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                buf.append(lines[i].lstrip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + inline(" ".join(buf)) + "</blockquote>")
            continue
        if line.strip() in ("---", "***"):
            out.append("<hr>")
            i += 1
            continue
        # 段落：合并到下一个空行/块级元素
        buf = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^\s*(#{1,6}\s|\||[-*+]\s|\d+\.\s|>|```|---)", lines[i]):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>" + inline(" ".join(buf)) + "</p>")
    if in_code and code_buf:
        out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
    return "\n".join(out)


def shell(title: str, nav: str, body: str) -> str:
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>"
        '<header><div class="wrap"><h1>VC-Cheat-Typer · 文档站</h1>'
        f"<nav>{nav}</nav></div></header>"
        f'<div class="wrap"><article>{body}</article>'
        '<div class="foot">离线文档 · 由 tools/build_docs.py 生成 · 无外链依赖</div>'
        "</div></body></html>"
    )


def main() -> int:
    os.makedirs(SITE, exist_ok=True)
    sources = [("README.md", "首页 / README"), ("README.en.md", "English README"), ("CONTRIBUTING.md", "CONTRIBUTING")]
    for name in sorted(os.listdir(DOCS)):
        if name.endswith(".md"):
            sources.append((f"docs/{name}", name[:-3]))
    pages = []
    for path, label in sources:
        full = os.path.join(ROOT, path)
        with open(full, "r", encoding="utf-8") as fh:
            md = fh.read()
        out_name = "index.html" if path == "README.md" else path.split("/")[-1][:-3] + ".html"
        pages.append((out_name, label))
    nav = "".join(f'<a href="{n}">{html.escape(t)}</a>' for n, t in pages)
    for (path, label), (out_name, _) in zip(sources, pages):
        full = os.path.join(ROOT, path)
        with open(full, "r", encoding="utf-8") as fh:
            md = fh.read()
        doc = shell(label, nav, render(md))
        with open(os.path.join(SITE, out_name), "w", encoding="utf-8") as fh:
            fh.write(doc)
        print(f"  {out_name:<32} <- {path}")
    print(f"文档站生成完成：{SITE}（{len(pages)} 页）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
