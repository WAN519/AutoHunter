"""Scan an application form into questions, fill answers, inject the review panel.

Works by label text, not per-site field names, so one engine covers Greenhouse, Lever and Ashby.
Every control gets a stable `data-ah` key in DOM order; scanning again gives the same keys.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from .profile import CHOICE_KINDS, LETTER, RESUME, SIGNATURE, SKIP, pick_option

RISKY = re.compile(r"arbitration|non-?compete|non-?solicit|background (check|screen)|drug (test|screen)|"
                   r"credit check|class action|jury|waive", re.I)

SCAN_JS = r"""() => {
  // raw() keeps the * / ✱ markers so we can tell required questions; clean() drops them.
  const raw = el => el ? (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim() : '';
  const clean = s => (s || '').replace(/[*✱]/g, '').replace(/\s+/g, ' ').trim();
  const visible = e => {
    if (e.type === 'file') return true;
    const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    return r.width > 2 && r.height > 2 && cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0';
  };
  const ownLabel = e => {
    if (e.id) { const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`); if (raw(l)) return raw(l); }
    const ids = e.getAttribute('aria-labelledby');
    if (ids) { const t = ids.split(/\s+/).map(i => raw(document.getElementById(i))).join(' ').trim(); if (t) return t; }
    const l = e.closest('label'); if (raw(l)) return raw(l);
    return (e.getAttribute('aria-label') || '').trim();
  };
  // The question text for a group of options (or an unlabeled field): walk up the ancestors and
  // take the first title-like element that isn't itself an option.
  const TITLE = 'legend, .application-label, [class*="label" i], [class*="title" i], [class*="question-text" i], h3, h4';
  const groupLabel = (e, own) => {
    let a = e.parentElement;
    for (let i = 0; i < 8 && a && a !== document.body; i++, a = a.parentElement) {
      for (const c of a.querySelectorAll(TITLE)) {
        if (c.contains(e) || c.querySelector('input, textarea, select')) continue;
        // an option's own label ("Yes" / "No" next to another radio) is never the question
        const target = c.tagName === 'LABEL' && c.htmlFor ? document.getElementById(c.htmlFor) : null;
        if (target && /^(radio|checkbox)$/i.test(target.type || '')) continue;
        if (c.closest('label') && c.closest('label') !== c && c.closest('label').htmlFor) continue;
        const optLabel = l => { const t = l.htmlFor && document.getElementById(l.htmlFor); return t && /^(radio|checkbox)$/i.test(t.type || ''); };
        if ([...c.querySelectorAll('label[for]')].some(optLabel)) continue;  // a wrapper around an option label
        const t = raw(c);
        if (t && clean(t) !== clean(own) && t.length < 400) return t;
      }
    }
    return '';
  };
  const isReq = (e, label) => e.required || e.getAttribute('aria-required') === 'true' || /[*✱]/.test(label);
  const out = [], groups = {};
  let n = 0;
  for (const e of document.querySelectorAll('input, textarea, select')) {
    const type = (e.type || '').toLowerCase();
    if (['hidden', 'submit', 'button', 'reset', 'image', 'search'].includes(type)) continue;
    if (e.name === 'g-recaptcha-response' || e.closest('#autohunter-panel')) continue;
    const choice = type === 'radio' || type === 'checkbox';
    if (!choice && !visible(e)) continue;
    if (choice) {
      const own = ownLabel(e) || e.value;
      const gid = e.name || ('x' + (n++));
      if (!groups[gid]) {
        const gl = groupLabel(e, own);
        groups[gid] = {key: 'q' + out.length, kind: type, label: clean(gl || own), required: isReq(e, gl), options: []};
        out.push(groups[gid]);
      } else if (e.required) groups[gid].required = true;
      const g = groups[gid];
      e.dataset.ah = g.key; e.dataset.ahOpt = String(g.options.length);
      g.options.push(clean(own));
      continue;
    }
    const kind = e.tagName === 'SELECT' ? 'select' : e.tagName === 'TEXTAREA' ? 'textarea'
               : e.getAttribute('role') === 'combobox' ? 'combobox' : (type || 'text');
    const label = ownLabel(e) || groupLabel(e, '') || (e.placeholder || '');
    const q = {key: 'q' + out.length, kind, label: clean(label), required: isReq(e, label),
               hint: clean((e.id || '') + ' ' + (e.name || '')).slice(0, 60),
               options: kind === 'select' ? [...e.options].map(o => clean(o.text)).filter(t => t && !/^(select|choose|--)/i.test(t)) : []};
    e.dataset.ah = q.key;
    out.push(q);
  }
  return out;
}"""

CONFIRM_RE = re.compile(
    r"thank you for (applying|your (application|interest))|application (has been |was )?(successfully )?"
    r"(submitted|received)|we('ve| have) received your application|your application is (in|complete)", re.I)


def platform_of(url: str) -> str:
    host = urlparse(url).netloc
    for name in ("greenhouse", "lever", "ashbyhq", "myworkdayjobs"):
        if name in host:
            return {"ashbyhq": "ashby", "myworkdayjobs": "workday"}.get(name, name)
    return "other"


def base_url(url: str) -> str:
    """The posting URL without the apply-page suffix, used to match tabs to a pending fill."""
    u = url.split("?")[0].split("#")[0].rstrip("/")
    m = re.match(r"(https://[^/]+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)/job/[^/]+/([^/]+)", u)
    if m:  # Workday: the location segment changes between pages ("US-CA" vs "US%2C-CA"); key on site + job slug
        return f"{m.group(1)}/{m.group(2)}/job/{m.group(3)}"
    return re.sub(r"/(apply(/[^/]+)?|application|confirmation|thanks|thank[-_]you|login)$", "", u)


def form_url(url: str) -> str:
    p, b = platform_of(url), base_url(url)
    return {"ashby": b + "/application", "lever": b + "/apply"}.get(p, b)


def is_confirmation(url: str, body: str) -> bool:
    if re.search(r"/(confirmation|thanks|thank[-_]you|submitted)(\b|/|$)", url, re.I):
        return True
    if platform_of(url) == "ashby" and re.search(r"(^|\n)\s*Success\s*(\n|$)", body):
        return True
    return bool(CONFIRM_RE.search(body))


def open_form(context, url: str):
    from .browser import find_page
    page = find_page(context, base_url(url))
    if page is None:
        page = context.new_page()
    target = form_url(url)
    page.goto(target, wait_until="networkidle", timeout=60000)  # always a clean form
    page.bring_to_front()
    page.wait_for_timeout(1500)
    if platform_of(url) == "greenhouse":  # the form sits below the JD; some boards hide it behind a button
        btn = page.locator("button:has-text('Apply'), a:has-text('Apply for this job')").first
        try:
            if btn.is_visible(timeout=1000) and not page.locator("#first_name").count():
                btn.click()
                page.wait_for_timeout(1500)
        except Exception:
            pass
    return page


VISIBLE_OPTIONS_JS = r"""(key) => {
  const box = document.querySelector(`[data-ah="${key}"]`);
  const id = box && (box.getAttribute('aria-controls') || box.getAttribute('aria-owns'));
  const scope = (id && document.getElementById(id)) || document;
  return [...scope.querySelectorAll('[role=option]')]
    .filter(o => { const r = o.getBoundingClientRect(); return r.height > 0 && r.width > 0; })
    .map(o => (o.innerText || '').trim()).filter(Boolean);
}"""


CLICK_OPTION_JS = r"""([key, text]) => {
  const box = document.querySelector(`[data-ah="${key}"]`);
  const id = box && (box.getAttribute('aria-controls') || box.getAttribute('aria-owns'));
  const scope = (id && document.getElementById(id)) || document;
  const opt = [...scope.querySelectorAll('[role=option]')].find(o => {
    const r = o.getBoundingClientRect();
    return r.height > 0 && (o.innerText || '').trim() === text;
  });
  if (!opt) return false;
  opt.scrollIntoView({block: 'nearest'});
  for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'])
    opt.dispatchEvent(new MouseEvent(t, {bubbles: true, cancelable: true, view: window}));
  return true;
}"""


def visible_options(page, key: str, limit: int = 300) -> list[str]:
    try:
        return page.evaluate(VISIBLE_OPTIONS_JS, key)[:limit]
    except Exception:
        return []


def combobox_options(page, q: dict) -> list[str]:
    loc = page.locator(f'[data-ah="{q["key"]}"]').first
    try:
        loc.click(timeout=3000)
        page.wait_for_timeout(500)
        texts = visible_options(page, q["key"])
        if not texts:  # type-to-search lists: collect what a few common letters reveal
            seen = {}
            for ch in "aeoi":
                loc.fill("")
                loc.press_sequentially(ch, delay=40)
                page.wait_for_timeout(900)
                for t in visible_options(page, q["key"]):
                    seen.setdefault(t, None)
            loc.fill("")
            texts = list(seen)
        page.keyboard.press("Escape")
        return texts
    except Exception:
        return []


def scan(page) -> list[dict]:
    qs = page.evaluate(SCAN_JS)
    for q in qs:
        if q["kind"] == "combobox" and not re.search(r"location|city|country|school|university", q["label"], re.I):
            q["options"] = combobox_options(page, q)
    return qs


def plan(questions: list[dict], profile) -> tuple[dict, list[dict]]:
    """(auto answers {key: {value, source}}, unknown questions)."""
    auto, unknown = {}, []
    for q in questions:
        value, source = profile.answer(q)
        if value is None:
            unknown.append(q)
            continue
        if value is SKIP or value is SIGNATURE:
            auto[q["key"]] = {"value": None, "source": "signature" if value is SIGNATURE else f"skip ({source})"}
            continue
        if q["kind"] in CHOICE_KINDS and isinstance(value, list) and q["options"]:
            chosen = pick_option(q["options"], value)
            if chosen is None:
                unknown.append(q)
                continue
            value = chosen
        elif q["kind"] in CHOICE_KINDS and isinstance(value, list):
            value = value[0]  # combobox without a readable list: type the first candidate
        auto[q["key"]] = {"value": value, "source": source}
    return auto, unknown


MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December"]


def _parse_date(text: str):
    from datetime import datetime as _dt
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%B %Y", "%b %Y"):
        try:
            return _dt.strptime(str(text).strip(), fmt)
        except ValueError:
            continue
    return None


CAL_JS = r"""() => {
  // The open calendar: a visible "Month YYYY" header and the visible day buttons near it.
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const re = /^(January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})$/;
  const head = [...document.querySelectorAll('div, span, h2, h3, button, [aria-live]')]
    .filter(e => vis(e) && e.children.length <= 2 && re.test((e.innerText || '').trim()))[0];
  return head ? head.innerText.trim() : '';
}"""


def _pick_calendar_date(page, loc, when) -> str | None:
    """Readonly date inputs with a pop-up calendar: open it, step months, click the day."""
    loc.click()
    page.wait_for_timeout(600)
    for _ in range(36):
        head = page.evaluate(CAL_JS)
        if not head:
            return "calendar didn't open"
        mon, year = head.split()
        cur = int(year) * 12 + MONTH_NAMES.index(mon)
        want = when.year * 12 + when.month - 1
        if cur == want:
            break
        step = 1 if want > cur else -1
        target = cur + step
        label = f"{MONTH_NAMES[target % 12]} {target // 12}"
        nav = page.locator(f"button[aria-label='{label}'], button:has-text('{label}')").locator("visible=true")
        if not nav.count():
            nav = page.locator("button[aria-label*='next' i]" if step > 0 else "button[aria-label*='prev' i]").locator("visible=true")
        if not nav.count():
            return "can't move the calendar"
        nav.first.click()
        page.wait_for_timeout(250)
    day = page.locator("button").filter(has_text=re.compile(rf"^\s*{when.day}\s*$")).locator("visible=true")
    for i in range(day.count()):
        b = day.nth(i)
        cls = (b.get_attribute("class") or "") + (b.get_attribute("aria-disabled") or "")
        if re.search(r"outside|other-month|disabled|true", cls):
            continue
        b.click()
        page.wait_for_timeout(300)
        return None if loc.input_value() else "day click didn't set a value"
    return "day not found"


def _overwrite(el, value) -> None:
    el.fill(str(value))
    return None


def _fill_one(page, q: dict, value, files: dict) -> str | None:
    """Fill one question. Returns None on success, else a short reason."""
    key, kind = q["key"], q["kind"]
    loc = page.locator(f'[data-ah="{key}"]')
    if kind == "file":
        path = files.get("resume") if value == RESUME else files.get("letter") if value == LETTER else value
        if not path or not Path(path).exists():
            return "file missing"
        loc.first.set_input_files(str(path))
        page.wait_for_timeout(3000)  # resume parsing may rewrite fields; we fill those after
        return None
    if kind == "checkbox" and len(q["options"]) == 1:  # a single box (e.g. "I agree"): just tick it
        el = page.locator(f'[data-ah="{key}"][data-ah-opt="0"]').first
        if not el.is_checked():
            rid = el.get_attribute("id")
            lab = page.locator(f'label[for="{rid}"]').locator("visible=true") if rid else None
            try:
                (lab.first if lab is not None and lab.count() else el).click(timeout=3000)
            except Exception:
                el.check(force=True)
        return None if el.is_checked() else "checkbox didn't take"
    if kind in ("radio", "checkbox"):
        wanted = value if isinstance(value, list) else [value]
        hit = False
        for w in wanted:
            opt = pick_option(q["options"], [w])
            if opt is None:
                continue
            i = q["options"].index(opt)
            el = page.locator(f'[data-ah="{key}"][data-ah-opt="{i}"]').first
            if not el.is_checked():
                # A real click on the label first: React-style pages ignore synthetic DOM clicks.
                rid = el.get_attribute("id")
                lab = page.locator(f'label[for="{rid}"]').locator("visible=true") if rid else None
                try:
                    (lab.first if lab is not None and lab.count() else el).click(timeout=3000)
                except Exception:
                    el.check(force=True)
                if not el.is_checked():
                    el.evaluate("e => e.click()")
            hit = el.is_checked() or hit
        return None if hit else "no matching option"
    if kind == "select":
        opt = pick_option(q["options"], value if isinstance(value, list) else [value])
        if opt is None:
            return "no matching option"
        loc.first.select_option(label=opt)
        return None
    if kind == "combobox":
        cands = [c for c in (value if isinstance(value, list) else [value]) if c]
        known = pick_option(q.get("options") or [], cands)
        if known:  # we already know the exact option: type that, not the first raw candidate
            cands = [known]
        el = loc.first
        tries = cands + [c.split(",")[0].split()[0] for c in cands if c.split()]
        for text in dict.fromkeys(tries):
            el.click()
            el.fill("")
            el.press_sequentially(str(text)[:40], delay=40)  # some lists only search on keystrokes
            opts = []
            for _ in range(10):
                page.wait_for_timeout(300)
                opts = visible_options(page, key)
                if opts:
                    break
            opt = pick_option(opts, cands) or pick_option(opts, [text])
            if opt and page.evaluate(CLICK_OPTION_JS, [key, opt]):  # exact text: "Washington" ≠ "Washington, D.C."
                page.wait_for_timeout(200)
                return None
        el.fill("")
        page.keyboard.press("Escape")
        return "no matching option"
    el = loc.first
    current = el.input_value() if kind not in ("file",) else ""
    if current and current.strip() and kind != "textarea" and current.strip() != str(value).strip():
        return None if el.get_attribute("readonly") is not None else _overwrite(el, value)
    if current and current.strip() == str(value).strip():
        return None  # already right: don't touch (it may also be the user's own edit)
    if el.get_attribute("readonly") is not None:
        when = _parse_date(value)
        if when:
            return _pick_calendar_date(page, el, when)
        return "read-only field"
    el.fill(str(value))
    return None


def fill(page, questions: list[dict], answers: dict, files: dict) -> tuple[list[str], list[str]]:
    """answers: {key: value}. Files first (resume parsing can overwrite fields).
    Returns (done labels, todo lines)."""
    done, todo = [], []
    by_key = {q["key"]: q for q in questions}
    order = sorted(answers, key=lambda k: 0 if by_key.get(k, {}).get("kind") == "file" else 1)
    for key in order:
        q, value = by_key.get(key), answers[key]
        if q is None or value is None:
            continue
        try:
            err = _fill_one(page, q, value, files)
        except Exception as e:  # a bad field must not stop the rest
            err = type(e).__name__
        short = q["label"][:50] or key
        if err:
            todo.append(f"“{short}” 没填上（{err}）")
        else:
            done.append(short)
    for q in questions:
        if q["required"] and q["key"] not in answers:
            todo.append(f"“{q['label'][:60]}” 必填，还没填")
    return done, todo


def inject_panel(page, data: dict) -> None:
    js = (Path(__file__).parent / "panel.js").read_text(encoding="utf-8")
    page.evaluate(js, data)


# ---------------------------------------------------------------- generic multi-step forms

NEXT_RE = re.compile(r"^\s*(next|continue|save (and|&) continue|proceed|next step)\s*[›>→]?\s*$", re.I)
SUBMIT_RE = re.compile(r"^\s*(submit( application)?|send application|finish|complete application)\s*$", re.I)

BUTTONS_JS = r"""() => [...document.querySelectorAll('button, input[type=submit], input[type=button], a[role=button]')]
  .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !e.disabled && !e.closest('#autohunter-panel'); })
  .map((e, i) => { e.dataset.ahBtn = String(i); return {i, text: (e.innerText || e.value || '').trim().replace(/\s+/g, ' ')}; })"""


def _buttons(page) -> list[dict]:
    return page.evaluate(BUTTONS_JS)


def open_generic(context, url: str):
    """Company-built application pages (e.g. Tesla): open the posting; if no form, click Apply."""
    def is_form(p) -> bool:
        qs = p.evaluate(SCAN_JS)
        return any(q["kind"] in ("file", "email") or re.search(r"e-?mail|first name", q["label"], re.I) for q in qs)

    ids = set(re.findall(r"\d{4,}", url))
    host = urlparse(url).netloc
    # A tab already on this job's application form (e.g. after a failed submit): start over there.
    page = next((p for p in context.pages if urlparse(p.url).netloc == host and ids & set(re.findall(r"\d{4,}", p.url))
                 and re.search(r"apply|application", p.url, re.I)), None)
    if page is None:
        page = context.new_page()
        page.goto(url, wait_until="load", timeout=60000)
        page.wait_for_timeout(3500)
    else:
        page.reload(wait_until="load")
        page.wait_for_timeout(3500)
    if not is_form(page):  # a posting page (maybe with a search box): go to its application
        link = page.locator("a, button").filter(has_text=re.compile(r"^\s*apply( now)?\s*$", re.I)).locator("visible=true")
        if link.count():
            href = link.first.get_attribute("href")
            if href and href.startswith(("http", "/")):
                page.goto(href if href.startswith("http") else f"{urlparse(page.url).scheme}://{host}{href}", wait_until="load")
            else:
                link.first.click()
                page.wait_for_load_state("load")
            page.wait_for_timeout(4000)
    page.bring_to_front()
    return page


def fill_multistep(page, profile, files: dict, label_answers: dict, max_steps: int = 8) -> dict:
    """Fill → Next → … until a Submit button shows up (never clicked) or a step can't advance.
    label_answers: {label: value} for questions the rules don't know (from Claude / the user)."""
    done_all, todo_all, unknown_all, consents = [], [], [], []
    filled: list[dict] = []
    letter_field = False
    step = 0
    for step in range(1, max_steps + 1):
        questions = scan(page)
        auto, unknown = plan(questions, profile)
        answers = {k: v["value"] for k, v in auto.items()}
        for q in list(unknown):
            if q["label"] in label_answers:
                answers[q["key"]] = label_answers[q["label"]]
                unknown.remove(q)
        for q in questions:
            src = auto.get(q["key"], {}).get("source")
            if src == "consent":
                text = q["options"][0] if len(q["options"]) == 1 and len(q["options"][0]) > len(q["label"]) else q["label"]
                consents.append(("⚠️ " if RISKY.search(text) else "") + text[:160])
            elif src == "signature":
                todo_all.append(f"✍️ 电子签名「{q['label']}」：请你自己输入法定姓名（等于签署上面的条款），我不会替你签")
        done, todo = fill(page, questions, answers, files)
        done_all += done
        if not files.get("letter") and any(q["kind"] in ("file", "textarea") and re.search(r"cover letter", q["label"] + " " + q.get("hint", "").replace("_", " "), re.I) for q in questions):
            letter_field = True
        by_key = {q["key"]: q for q in questions}
        for k, v in answers.items():
            q = by_key.get(k)
            if q and v is not None:
                shown = Path(files.get("resume", "")).name if v == RESUME else Path(files.get("letter", "")).name if v == LETTER else v
                filled.append({"step": step, "label": q["label"] or q.get("hint", ""), "kind": q["kind"],
                               "value": ", ".join(shown) if isinstance(shown, list) else str(shown)})
        unknown_all += [{"step": step, "label": q["label"], "kind": q["kind"], "options": q["options"][:30],
                         "required": q["required"]} for q in unknown if q["required"]]
        if any(q["required"] for q in unknown):
            todo_all += todo
            break
        if any(auto.get(q["key"], {}).get("source") == "signature" and q["required"] for q in questions):
            todo_all += todo
            break  # can't go past a required signature: the user signs, then clicks on
        btns = _buttons(page)
        if any(SUBMIT_RE.match(b["text"]) for b in btns) and not any(NEXT_RE.match(b["text"]) for b in btns):
            break  # the last step: the user reviews and submits
        nxt = next((b for b in btns if NEXT_RE.match(b["text"])), None)
        if not nxt:
            break
        before = page.url + str(len(questions)) + (questions[0]["label"] if questions else "")
        page.locator(f"[data-ah-btn='{nxt['i']}']").first.click()
        page.wait_for_timeout(4000)
        after_qs = page.evaluate(SCAN_JS)
        after = page.url + str(len(after_qs)) + (after_qs[0]["label"] if after_qs else "")
        if after == before:
            errs = page.evaluate("""() => [...document.querySelectorAll('[role=alert], [aria-invalid=true], .error, [class*=error i]')]
                .map(e => (e.innerText || '').trim()).filter(t => t && t.length < 200).slice(0, 5)""")
            todo_all.append("点 Next 没有前进" + (f"：{'; '.join(errs)}" if errs else ""))
            break
    return {"steps": step, "done": done_all, "todo": todo_all, "unknown": unknown_all, "consents": consents,
            "filled": filled, "needs_letter": letter_field,
            "at_submit": any(SUBMIT_RE.match(b["text"]) for b in _buttons(page))}
