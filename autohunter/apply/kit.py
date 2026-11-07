"""Manual-submit kit, for sites that reject submissions from an automated browser (e.g. Tesla).

The answers come from an auto-fill pass in the AutoHunter Chrome (reading and filling there is
fine; only the submit gets rejected). Then:
  · the apply page opens in the user's OWN Chrome (default profile, no automation attached)
  · a cheat sheet opens next to it: every question with its answer and a copy button, the resume
    file, consent notes, the signature reminder
The user pastes and submits (a few minutes). The site is remembered in me/output/manual_sites.json
so next time the hotkey goes straight to the kit.
"""
from __future__ import annotations

import html
import json
import platform
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from .browser import chrome_binary

SIGN_LABEL = ("legal name", "full legal name", "signature", "electronic signature", "e-signature")


def fill_data(form: dict, resume: str) -> dict:
    """What the bookmarklet reads from the clipboard: label → answer (no files, no signatures)."""
    answers = []
    for f in form.get("filled", []):
        if f["kind"] == "file":
            continue
        label = f["label"]
        if f["kind"] == "checkbox":
            label = f["value"]  # a single box ("I acknowledge … Arbitration Agreement"): match it by its own text
        elif label.strip().lower() in SIGN_LABEL:
            continue  # never the signature
        answers.append({"label": label, "value": f["value"], "kind": f["kind"]})
    return {"autohunter": 1, "answers": answers, "resume": resume}


def bookmarklet() -> str:
    from urllib.parse import quote
    js = (Path(__file__).parent / "fillscript.js").read_text(encoding="utf-8")
    js = "\n".join(l for l in js.splitlines() if not l.strip().startswith("//"))
    return "javascript:" + quote(js, safe="")


def install_page(me: Path) -> Path:
    page = me / "output" / "bookmarklet.html"
    page.write_text(f"""<!doctype html><meta charset="utf-8"><title>安装 AutoHunter 填表书签</title>
<style>body{{font:15px/1.6 -apple-system,"PingFang SC",sans-serif;max-width:620px;margin:40px auto;padding:0 16px}}
a.bm{{display:inline-block;background:#0071e3;color:#fff;padding:10px 18px;border-radius:10px;text-decoration:none;font-weight:600}}</style>
<h2>安装「AutoHunter 填表」书签（只要一次）</h2>
<ol><li>按 ⌘⇧B 显示书签栏。</li>
<li>把下面这个蓝色按钮<b>拖</b>到书签栏上（别点它）：<br><br><a class="bm" href="{bookmarklet()}">AutoHunter 填表</a></li>
<li>以后在申请页上点这个书签，就会用剪贴板里的答案填当前这一页。第一次 Chrome 会问能否读取剪贴板，选「允许」。</li></ol>
<p>它只在你点的时候、在当前页面里运行，不会点 Next / Submit，不填签名和文件。</p>""", encoding="utf-8")
    return page


def copy_to_clipboard(text: str) -> None:
    if platform.system() == "Darwin":
        subprocess.run(["pbcopy"], input=text.encode("utf-8"))


def _sites_path(me: Path) -> Path:
    return me / "output" / "manual_sites.json"


def manual_sites(me: Path) -> list[str]:
    p = _sites_path(me)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def is_manual(me: Path, url: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in manual_sites(me))


def remember(me: Path, url: str) -> None:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    sites = manual_sites(me)
    if host not in sites:
        _sites_path(me).write_text(json.dumps(sites + [host], indent=2), encoding="utf-8")


def open_in_users_chrome(url: str) -> None:
    """The user's everyday Chrome: run Chrome WITHOUT AutoHunter's --user-data-dir, so the URL goes
    to the default-profile instance (never the automated one)."""
    if platform.system() == "Darwin":
        subprocess.Popen([chrome_binary(), url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    else:
        import webbrowser
        webbrowser.open(url)


def build(me: Path, folder: Path, form: dict, job: dict, resume: str) -> Path:
    filled = form.get("filled", [])
    data_json = json.dumps(fill_data(form, resume), ensure_ascii=False)
    install_uri = install_page(me).resolve().as_uri()
    summary = {}
    if (folder / "summary.json").exists():
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    rows, step = [], None
    for f in filled:
        if f["step"] != step:
            step = f["step"]
            rows.append(f'<tr class="step"><td colspan="3">第 {step} 步</td></tr>')
        v = html.escape(f["value"])
        kind = "（上传文件）" if f["kind"] == "file" else "（勾选）" if f["kind"] == "checkbox" else ""
        rows.append(f'<tr><td>{html.escape(f["label"][:140])}</td><td class="v">{v} <span class="k">{kind}</span></td>'
                    f'<td><button onclick="cp(this)" data-v="{v}">复制</button></td></tr>')
    unknown = "".join(f"<li>{html.escape(u['label'][:140])}</li>" for u in form.get("generic_unknown", []))
    resume_uri = Path(resume).resolve().as_uri() if resume else ""
    page = folder / "manual_kit.html"
    page.write_text(f"""<!doctype html><meta charset="utf-8"><title>手动提交 · {html.escape(job.get('company', ''))}</title>
<style>body{{font:14px/1.5 -apple-system,"PingFang SC",sans-serif;margin:0;background:#f5f5f7}} main{{max-width:820px;margin:20px auto;padding:0 14px}}
.box{{background:#fff;border-radius:12px;padding:12px 16px;margin:10px 0}} table{{width:100%;border-collapse:collapse}}
td{{padding:6px 8px;border-bottom:1px solid #eee;vertical-align:top}} td.v{{font-weight:600}} .k{{color:#6e6e73;font-weight:400}}
tr.step td{{background:#f0f0f3;font-weight:600}} button{{border:0;background:#0071e3;color:#fff;border-radius:6px;padding:3px 10px;cursor:pointer}}
.warn{{background:#fff8e1}}</style>
<main><h2>手动提交：{html.escape(job.get('company', ''))} · {html.escape(job.get('title', ''))}</h2>
<div class="box warn">这家网站会拒绝自动化浏览器的提交，所以申请页已经在<b>你自己的 Chrome</b> 里打开了。<br>
<b>最快的办法：</b>在申请页点书签栏上的 <b>「AutoHunter 填表」</b>，它会把这一页填好 → 你点 Next → 下一页再点一次书签 → … → 你提交。
填表数据已经复制到剪贴板了（被别的内容覆盖了就点这里 → <button onclick="copyData(this)">复制填表数据</button>）。
还没装书签？<a href="{install_uri}">点这里安装</a>（拖一下就好）。<br>
书签填不了的（上传简历、日历日期、<b>电子签名</b>）照下面手动填。</div>
<div class="box"><b>📄 简历文件：</b> <code>{html.escape(resume)}</code>
{f' · <a href="{resume_uri}">打开</a>' if resume_uri else ''}<br><span class="k">在申请页点上传，选这个文件（Finder 里 ⌘⇧G 粘贴路径）。</span>
{('<br><b>简历改动：</b>' + html.escape((summary.get('resume') or {}).get('oneline', ''))) if summary else ''}</div>
<div class="box"><table>{''.join(rows) or '<tr><td>还没有记录到答案（先自动填一遍）</td></tr>'}</table></div>
{f'<div class="box warn"><b>还没答案、要你自己填的：</b><ul>{unknown}</ul></div>' if unknown else ''}
</main><script>function cp(b){{navigator.clipboard.writeText(b.dataset.v);b.textContent='已复制';setTimeout(()=>b.textContent='复制',1200)}}
const DATA = {json.dumps(data_json)};
function copyData(b){{navigator.clipboard.writeText(DATA);b.textContent='已复制';setTimeout(()=>b.textContent='复制填表数据',1500)}}</script>""",
                    encoding="utf-8")
    return page
