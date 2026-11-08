"""Workday application flow: sign in / create the account, then fill step by step up to Review.

Workday pages are built from `data-automation-id` widgets, the same on every tenant:
  formField-<name>   one question (label + control)
  text inputs, radios, single checkboxes, listbox buttons (aria-haspopup=listbox),
  multiselect prompts (multiSelectContainer, sometimes two levels), date sections, file upload.
Each step: scan → answer by label (profile.Profile rules) → fill → "Save and Continue".
Stops at Review (never submits), or when a required question has no answer yet.

Accounts: one per tenant (tenants disqualify duplicate profiles), remembered in
me/output/workday_accounts.json. Never fill the hidden `beecatcher` honeypot.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .profile import CHOICE_KINDS, LETTER, RESUME, SKIP, pick_option

SCAN_JS = r"""() => {
  const clean = s => (s || '').replace(/[*✱]/g, '').replace(/\s+/g, ' ').trim();
  const out = [];
  let n = 0;
  for (const f of document.querySelectorAll('[data-automation-id^="formField-"]')) {
    if (!f.offsetParent || f.closest('[data-automation-id^="formField-"]') !== f && f.parentElement.closest('[data-automation-id^="formField-"]')) continue;
    const rawLabel = ((f.querySelector('label, legend') || {}).innerText || '').trim();
    const key = 'w' + (n++);
    f.dataset.ah = key;
    let kind = 'text', options = [], value = '';
    const radios = [...f.querySelectorAll('input[type=radio]')];
    const boxes = [...f.querySelectorAll('input[type=checkbox]')];
    const lb = f.querySelector('button[aria-haspopup=listbox]');
    const ms = f.querySelector('[data-automation-id=multiSelectContainer], [data-uxi-widget-type=multiselect]');
    const date = f.querySelector('[data-automation-id^=dateSection]');
    const file = f.querySelector('input[type=file]');
    const ta = f.querySelector('textarea');
    if (file) kind = 'file';
    else if (radios.length) { kind = 'radio'; options = radios.map(r => clean((document.querySelector(`label[for="${CSS.escape(r.id)}"]`) || r.parentElement).innerText)); value = String(radios.findIndex(r => r.checked)); }
    else if (lb) { kind = 'listbox'; value = clean(lb.innerText); }
    else if (ms) { kind = 'multiselect'; value = [...f.querySelectorAll('[data-automation-id=selectedItem]')].map(e => clean(e.innerText)).join('; '); }
    else if (date) kind = 'date';
    else if (boxes.length === 1) { kind = 'checkbox'; options = [clean(rawLabel) || 'Yes']; value = boxes[0].checked ? 'checked' : ''; }
    else if (boxes.length > 1) { kind = 'checkbox'; options = boxes.map(b => clean((document.querySelector(`label[for="${CSS.escape(b.id)}"]`) || b.parentElement).innerText)); }
    else if (ta) { kind = 'textarea'; value = ta.value; }
    else { const i = f.querySelector('input:not([type=hidden])'); if (!i) continue; value = i.value; if (i.getAttribute('data-automation-id') === 'beecatcher') continue; }
    const grp = f.closest('[role=group][aria-labelledby]');
    out.push({key, field: f.getAttribute('data-automation-id').slice(10), kind, label: clean(rawLabel),
              group: grp ? grp.getAttribute('aria-labelledby') : '',
              required: /\*/.test(rawLabel) || !!f.querySelector('[aria-required=true], [required]'), options, value});
  }
  return out;
}"""

POPUP_JS = r"""() => {
  // Options of the popup that's open now (listbox or multiselect prompt), not selected chips.
  const vis = e => { const r = e.getBoundingClientRect(); return r.height > 0 && r.width > 0; };
  const lists = [...document.querySelectorAll('[role=listbox], [data-automation-id=activeListContainer]')].filter(vis);
  const scope = lists.length ? lists[lists.length - 1] : document;
  return [...scope.querySelectorAll('[role=option], [data-automation-id=promptOption]')].filter(vis)
    .filter(o => !o.closest('[data-automation-id=selectedItem]'))
    .map(o => (o.innerText || '').trim().replace(/\s+/g, ' ')).filter(t => t && t !== 'Select One');
}"""

CLICK_POPUP_JS = r"""(text) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.height > 0 && r.width > 0; };
  const lists = [...document.querySelectorAll('[role=listbox], [data-automation-id=activeListContainer]')].filter(vis);
  const scope = lists.length ? lists[lists.length - 1] : document;
  const o = [...scope.querySelectorAll('[role=option], [data-automation-id=promptOption]')].filter(vis)
    .find(o => (o.innerText || '').trim().replace(/\s+/g, ' ') === text);
  if (!o) return false;
  o.scrollIntoView({block: 'nearest'});
  for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'])
    o.dispatchEvent(new MouseEvent(t, {bubbles: true, cancelable: true, view: window}));
  return true;
}"""

def _click_option(page, text: str) -> bool:
    """Real mouse click on the visible popup option with exactly this text (Workday ignores
    synthetic DOM events on its prompts)."""
    loc = page.locator("[data-automation-id=promptOption], [role=option]").filter(
        has_text=re.compile(rf"^\s*{re.escape(text)}\s*$")).locator("visible=true")
    for i in range(min(loc.count(), 4)):
        el = loc.nth(i)
        if el.get_attribute("data-automation-id") == "selectedItem":
            continue
        try:
            el.click(timeout=3000)
            return True
        except Exception:
            continue
    return page.evaluate(CLICK_POPUP_JS, text)


KIND_FOR_PROFILE = {"listbox": "select", "multiselect": "combobox", "radio": "radio", "checkbox": "checkbox",
                    "text": "text", "textarea": "textarea", "file": "file", "date": "text"}


# ---------------------------------------------------------------- accounts

def _accounts_path(me: Path) -> Path:
    return me / "output" / "workday_accounts.json"


def accounts(me: Path) -> dict:
    p = _accounts_path(me)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def remember_account(me: Path, tenant: str, email: str, status: str) -> None:
    d = accounts(me)
    d[tenant] = {**d.get(tenant, {}), "email": email, "status": status,
                 "updated": datetime.now().isoformat(timespec="seconds")}
    d[tenant].setdefault("created", d[tenant]["updated"])
    _accounts_path(me).write_text(json.dumps(d, indent=2), encoding="utf-8")


def tenant_of(url: str) -> str:
    return re.sub(r"\.myworkdayjobs\.com.*", "", url.split("//")[-1])


def _id(page, name: str):
    return page.locator(f"[data-automation-id='{name}']").first


def _click(page, name: str) -> None:
    # Workday puts a transparent "click_filter" over buttons; a forced click goes through it.
    _id(page, name).click(force=True)


def current_step(page) -> str:
    try:
        t = _id(page, "progressBarActiveStep").inner_text(timeout=3000)
        return re.sub(r"\s+", " ", re.sub(r"current step \d+ of \d+", "", t)).strip()
    except Exception:
        return ""


def open_application(page, url: str) -> None:
    page.goto(url, wait_until="networkidle", timeout=60000)
    if "/apply" in page.url:
        return
    if _id(page, "continueButton").count():  # a saved draft for this posting: resume it
        _click(page, "continueButton")
        page.wait_for_timeout(4000)
        return
    _click(page, "adventureButton")
    page.wait_for_timeout(2500)
    for choice in ("applyManually", "useMyLastApplication"):
        if _id(page, choice).count():
            _click(page, choice)
            break
    page.wait_for_timeout(3500)


def sign_in_or_create(page, me: Path, email: str, password: str, log: list[str]) -> bool:
    """Returns True once past the account step."""
    tenant = tenant_of(page.url)
    if not (_id(page, "signInContent").count() or _id(page, "SignInWithEmailButton").count()):
        return True  # already signed in
    if _id(page, "SignInWithEmailButton").count():
        _click(page, "SignInWithEmailButton")
        page.wait_for_timeout(1500)
    known = accounts(me).get(tenant)
    creating = not known and _id(page, "createAccountLink").count()
    if creating:
        _click(page, "createAccountLink")
        page.wait_for_timeout(1500)
    if not _id(page, "verifyPassword").count() and _id(page, "createAccountCheckbox").count():
        creating = True  # the tenant opened straight on Create Account
    _id(page, "email").fill(email)
    _id(page, "password").fill(password)
    if creating:
        _id(page, "verifyPassword").fill(password)
        cb = _id(page, "createAccountCheckbox")
        if cb.count() and not cb.is_checked():
            cb.check(force=True)
            log.append("☑️ 同意创建候选人账号：你的资料会存在这家公司的系统里，可以随时要求删除；同时接受其条款和隐私政策")
        if _id(page, "beecatcher").count() and _id(page, "beecatcher").input_value():
            raise RuntimeError("honeypot field is filled; refusing to continue")
        _click(page, "createAccountSubmitButton")
    else:
        _click(page, "signInSubmitButton")
    page.wait_for_timeout(6000)
    errors = page.evaluate("() => [...document.querySelectorAll('[data-automation-id*=rror], [role=alert]')]"
                           ".map(e => e.innerText.trim()).filter(Boolean)")
    if errors:
        log.append("账号步骤出错：" + "; ".join(errors[:2]))
        if any(re.search(r"verif", e, re.I) for e in errors):
            remember_account(me, tenant, email, "needs-verification")
        return False
    remember_account(me, tenant, email, "created" if creating else "signed-in")
    return bool(current_step(page)) and "sign" not in current_step(page).lower()


def verify_from_gmail(page, me: Path, company: str, since_iso: str, log: list[str]) -> bool:
    """Workday sometimes needs the account verified by email: read the link from Gmail."""
    from .. import sheets
    msg = sheets.verification(me, hint=company.lower(), since_iso=since_iso, wait=180)
    if not msg or not msg.get("links"):
        log.append("没在 Gmail 里找到验证邮件（等了 3 分钟）")
        return False
    tab = page.context.new_page()
    tab.goto(msg["links"][0], wait_until="networkidle", timeout=60000)
    tab.close()
    log.append(f"已用 Gmail 里的验证邮件激活账号（{msg.get('subject', '')[:40]}）")
    return True


# ---------------------------------------------------------------- fields

def scan(page) -> list[dict]:
    return page.evaluate(SCAN_JS)


def _profile_answer(profile, q: dict):
    label = q["label"].lower()
    # Workday-specific labels the generic rules don't know.
    if re.search(r"phone device type", label):
        return ["Mobile", "Cell", "Cellular", "Home Cellular", "Personal Cell", "Mobile Phone"], "rule"
    if re.search(r"country phone code", label):
        return SKIP, "rule"  # defaults to the country; changing it wipes the number
    if re.search(r"phone extension|address line 2|middle name|suffix|prefix|^title$", label):
        return SKIP, "rule"
    if re.search(r"i have a preferred name", label):
        return SKIP, "rule"
    if re.search(r"^(address line 1|postal code|zip)", label):
        v = profile.c.get("address_line1" if "address" in label else "postal_code")
        return (v, "settings") if v else (SKIP if not q["required"] else None, "rule")
    if re.search(r"linkedin", label):
        v = profile.c.get("linkedin", "")
        m = re.search(r"linkedin\.com/in/([\w-]+)", v)
        return (f"https://www.linkedin.com/in/{m.group(1)}/" if m else v) or None, "settings"
    if re.search(r"phone number", label):
        digits = re.sub(r"\D", "", profile.c.get("phone", ""))
        return (digits[-10:] or None), "settings"
    pq = {**q, "kind": KIND_FOR_PROFILE.get(q["kind"], "text")}
    return profile.answer(pq)


def _listbox(page, key: str, cands: list[str]) -> str | None:
    btn = page.locator(f"[data-ah='{key}'] button[aria-haspopup=listbox]").first
    opts = []
    # The popup sometimes renders late (open it again once); near the bottom of a step a
    # force-click can land on the sticky footer, so centre the button first and fall back
    # to opening it from the keyboard.
    for wait, how in ((700, "click"), (1500, "click"), (1500, "key")):
        try:
            btn.evaluate("b => b.scrollIntoView({block: 'center'})")
        except Exception:
            pass
        if how == "click":
            btn.click(force=True)
        else:
            btn.focus()
            btn.press("Enter")
            page.wait_for_timeout(500)
            if not page.evaluate(POPUP_JS):
                btn.press("ArrowDown")
        page.wait_for_timeout(wait)
        opts = page.evaluate(POPUP_JS)
        if opts:
            break
        page.keyboard.press("Escape")
    opt = pick_option(opts, cands)
    if opt and _click_option(page, opt):
        page.wait_for_timeout(500)
        return None
    page.keyboard.press("Escape")
    return f"no matching option in {opts[:6]}"


def _multiselect(page, key: str, cands: list[str], guess: bool = True) -> str | None:
    box = page.locator(f"[data-ah='{key}'] input").first
    box.click(force=True)
    page.wait_for_timeout(900)
    for _level in range(3):  # categories → sub-options
        opts = list(dict.fromkeys(page.evaluate(POPUP_JS)))
        opt = pick_option(opts, cands, loose=False)
        guessed = False
        if not opt and opts and _level > 0:
            # Inside the chosen category: the company's own site ("NVIDIA.COM"), else careers / .com.
            company = tenant_of(page.url).split(".")[0].lower()
            opt = next((o for o in opts if company and company in o.lower()), None) \
                or next((o for o in opts if re.search(r"career|website|\.com\b", o, re.I)), None)
            if not opt:
                opt, guessed = opts[0], True
        if not opt:
            for c in cands:  # type-to-search prompts
                if not c:
                    continue
                box.fill(c)
                box.press("Enter")
                page.wait_for_timeout(1500)
                opts = list(dict.fromkeys(page.evaluate(POPUP_JS)))
                opt = pick_option(opts, cands, loose=False)
                if not opt and opts and guess:
                    # Closest search result; say so, since it isn't the user's exact wording.
                    import difflib
                    best = difflib.get_close_matches(c, opts, n=1, cutoff=0.5)
                    opt, guessed = (best[0], True) if best else (None, False)
                if opt:
                    break
                seen_opts = opts
        if not opt and not guess:
            page.keyboard.press("Escape")
            box.fill("")
            return f"none of {cands} exists here; options for “{cands[0].split()[0]}”: {locals().get('seen_opts', opts)[:8]}"
        if not opt or not _click_option(page, opt):
            page.keyboard.press("Escape")
            return f"no matching option in {opts[:6]}"
        page.wait_for_timeout(900)
        if page.locator(f"[data-ah='{key}'] [data-automation-id=selectedItem]").count():
            page.keyboard.press("Escape")
            return f"guess: 选了 “{opt}”，请确认" if guessed else None
    page.keyboard.press("Escape")
    return "couldn't select"


def fill_field(page, q: dict, value, files: dict) -> str | None:
    key, kind = q["key"], q["kind"]
    root = page.locator(f"[data-ah='{key}']").first
    cands = value if isinstance(value, list) else [value]
    if kind == "file":
        path = files.get("resume") if value == RESUME else files.get("letter") if value == LETTER else value
        if not path:
            return "file missing"
        root.locator("input[type=file]").first.set_input_files(str(path))
        page.wait_for_timeout(5000)
        return None
    if kind == "listbox":
        return _listbox(page, key, [str(c) for c in cands])
    if kind == "multiselect":
        return _multiselect(page, key, [str(c) for c in cands])
    if kind == "radio":
        opt = pick_option(q["options"], [str(c) for c in cands])
        if not opt:
            return "no matching option"
        i = q["options"].index(opt)
        radio = root.locator("input[type=radio]").nth(i)
        rid = radio.get_attribute("id")
        (page.locator(f"label[for='{rid}']").first if rid else radio).click(force=True)
        return None if radio.is_checked() else "radio didn't take"
    if kind == "checkbox":
        boxes = root.locator("input[type=checkbox]")
        if boxes.count() == 1:
            if not boxes.first.is_checked():
                boxes.first.check(force=True)
            return None
        hit = False
        for c in cands:
            opt = pick_option(q["options"], [str(c)])
            if opt:
                boxes.nth(q["options"].index(opt)).check(force=True)
                hit = True
        return None if hit else "no matching option"
    if kind == "date":
        return "date fields: not automated yet"
    el = root.locator("textarea, input:not([type=hidden])").first
    el.fill(str(value))
    el.press("Tab")
    return None


# ---------------------------------------------------------------- My Experience

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _month_year(text: str) -> tuple[str, str] | None:
    m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{4})", text or "")
    if m and m.group(1).lower() in MONTHS:
        return f"{MONTHS[m.group(1).lower()]:02d}", m.group(2)
    y = re.search(r"(\d{4})", text or "")
    return ("", y.group(1)) if y else None


def _panel(page, section: str, i: int):
    """The i-th (1-based) entry panel of a section, adding entries as needed."""
    sel = f"[role=group][aria-labelledby='{section}-{i}-panel']"
    if not page.locator(sel).count():
        sec = page.locator(f"[role=group][aria-labelledby='{section}-section']").first
        sec.locator("button[data-automation-id=add-button]").last.click(force=True)
        page.wait_for_timeout(1500)
    return page.locator(sel).first


def _set_text(panel, field: str, value: str) -> None:
    el = panel.locator(f"[data-automation-id='formField-{field}'] input, [data-automation-id='formField-{field}'] textarea").first
    if el.count():
        el.fill(value)
        el.press("Tab")


def _set_date(panel, field: str, text: str) -> bool:
    """Workday date = MM / YYYY spinbuttons behind a display layer: click the display, then type;
    the month section auto-advances to the year."""
    my = _month_year(text)
    f = panel.locator(f"[data-automation-id='formField-{field}']").first
    if not my or not f.count():
        return False
    month, year = my
    page = panel.page
    first = f.locator("[data-automation-id=dateSectionMonth-display]")
    if not (month and first.count()):
        first = f.locator("[data-automation-id=dateSectionYear-display]")
    first.first.click()
    page.wait_for_timeout(200)
    page.keyboard.type((month if first.first.get_attribute("data-automation-id").startswith("dateSectionMonth") else "") + year, delay=70)
    page.keyboard.press("Tab")
    page.wait_for_timeout(200)
    return True


def fill_experience(page, me: Path, profile, files: dict, skills: list[str], log: list[str]) -> list[str]:
    """Work experience, education, skills, resume, links from me/experience.json."""
    path = me / "experience.json"
    if not path.exists():
        return ["没有 me/experience.json：工作经历和学历要你自己填"]
    data = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    for i, job in enumerate(data.get("work", []), 1):
        try:
            panel = _panel(page, "Work-Experience", i)
            if panel.locator("[data-automation-id='formField-jobTitle'] input").input_value():
                continue  # already there (previous run / resume parsing): leave the user's version
            _set_text(panel, "jobTitle", job["title"])
            _set_text(panel, "companyName", job["company"])
            if job.get("location"):
                _set_text(panel, "location", job["location"])
            _set_date(panel, "startDate", job["from"])
            if re.search(r"present|now|current", job.get("to", ""), re.I):
                panel.locator("[data-automation-id='formField-currentlyWorkHere'] input").first.check(force=True)
            else:
                _set_date(panel, "endDate", job["to"])
            _set_text(panel, "roleDescription", "\n".join(f"• {b}" for b in job.get("bullets", []))[:2000])
        except Exception as e:
            problems.append(f"工作经历 {i}（{job.get('company')}）没填完：{type(e).__name__}")
    for i, edu in enumerate(data.get("education", []), 1):
        try:
            panel = _panel(page, "Education", i)
            deg = panel.locator("[data-automation-id='formField-degree']").first
            deg_btn = deg.locator("button[aria-haspopup=listbox]").first
            deg_empty = deg.count() > 0 and (
                not deg_btn.count() or (deg_btn.inner_text() or "").strip() in ("", "Select One"))
            if panel.locator("[data-automation-id='formField-schoolName'] input").input_value():
                # Already there (previous run / resume parsing): keep it, but a required
                # Degree left empty would block the step, so fill just that.
                if not deg_empty:
                    continue
                only_degree = True
            else:
                only_degree = False
                _set_text(panel, "schoolName", edu["school"])
            k = deg.get_attribute("data-ah") if deg.count() else None
            if deg.count() and not k:
                deg.scroll_into_view_if_needed()
                scan(page)  # key the fields again (panels added / rendered since the last scan)
                k = deg.get_attribute("data-ah")
            if deg.count() and not k:
                problems.append(f"学历 {i} 的 Degree：找不到下拉框")
            if k and deg_empty:
                from .profile import DEGREES
                key = {"Master's": "masters", "Bachelor's": "bachelors", "PhD": "phd"}.get(edu.get("degree"), "")
                err = _listbox(page, k, DEGREES.get(key, [edu.get("degree", "")]) + ["Master of Science", "Bachelor of Engineering", "Bachelor of Science"])
                if err:
                    problems.append(f"学历 {i} 的 Degree：{err}")
            if only_degree:
                continue
            k = panel.locator("[data-automation-id='formField-fieldOfStudy']").first.get_attribute("data-ah")
            if k:
                field = edu.get("field", "")
                # The user's own field first, then the alternates they approved, never a guess.
                err = _multiselect(page, k, [field] + edu.get("field_alternates", []), guess=False)
                if err:
                    problems.append(f"学历 {i} 的 Field of Study（你的是 {field}）：{err.replace('guess:', '').strip()}")
            to = profile.graduation() if edu.get("to") == "graduation_setting" else edu.get("to", "")
            _set_date(panel, "firstYearAttended", edu.get("from", ""))
            _set_date(panel, "lastYearAttended", to)
        except Exception as e:
            problems.append(f"学历 {i}（{edu.get('school')}）没填完：{type(e).__name__}")
    sk = page.locator("[data-automation-id='formField-skills'] input").first
    added = 0
    for skill in skills[:15]:
        try:
            sk.click(force=True)
            sk.fill(skill)
            sk.press("Enter")
            page.wait_for_timeout(1200)
            opts = list(dict.fromkeys(page.evaluate(POPUP_JS)))
            opt = pick_option(opts, [skill])
            if opt and _click_option(page, opt):
                added += 1
            page.keyboard.press("Escape")
        except Exception:
            pass
    if skills:
        log.append(f"技能加了 {added}/{min(len(skills), 15)} 个（Workday 技能库里没有的会跳过）")
    sec = page.locator("[role=group][aria-labelledby='Resume/CV-section']").first
    up = sec.locator("input[type=file]").first
    if files.get("resume") and up.count():
        # Workday appends uploads: remove what's there (earlier runs, other versions) so exactly
        # one resume, the current one, goes in.
        removed = 0
        for _ in range(10):
            d = sec.locator("button[data-automation-id=delete-file]")
            if not d.count():
                break
            d.first.click(force=True)
            page.wait_for_timeout(1200)
            removed += 1
        up.set_input_files(files["resume"])
        page.wait_for_timeout(5000)
        n = sec.locator("[data-automation-id=file-upload-item]").count()
        log.append(f"简历：上传了 {Path(files['resume']).name}" + (f"（先删掉了之前的 {removed} 份）" if removed else ""))
        if n != 1:
            problems.append(f"简历区现在有 {n} 份文件，应该只有 1 份")
    elif not files.get("resume"):
        problems.append("简历文件没传（没有生成好的简历）")
    return problems


def page_errors(page) -> list[str]:
    return page.evaluate("""() => [...document.querySelectorAll(
        '[data-automation-id=errorMessage], [data-automation-id=errorBanner] li, [data-automation-id*=inputError], [data-automation-id=inputAlert], [data-automation-id=errorHeading]')]
        .map(e => e.innerText.trim()).filter(Boolean).slice(0, 8)""")


def fill_step(page, profile, files: dict, extra: dict, log: list[str]) -> tuple[list[dict], list[str]]:
    """Fill what we can on the current step. Returns (unanswered required questions, problems)."""
    unknown, problems = [], []
    step = current_step(page)
    if re.search(r"experience", step, re.I):
        problems += fill_experience(page, profile_me(profile), profile, files, extra.get("_skills", []), log)
    for q in scan(page):
        if re.search(r"Work-Experience|Education|Skills-section|Resume/CV", q.get("group", "")):
            continue  # handled by fill_experience
        key_label = f"{step}::{q['label']}"
        if key_label in extra:
            value, source = extra[key_label], "provided"
        elif q["value"] and q["value"] not in ("Select One", "0 items selected", "-1", ""):
            continue  # already filled (by the tenant, resume parsing or a previous run)
        else:
            value, source = _profile_answer(profile, q)
        if value is SKIP:
            continue
        if value is None:
            if q["required"]:
                unknown.append({**q, "step": step})
            continue
        if q["kind"] in CHOICE_KINDS | {"listbox", "multiselect"} and q["options"] and isinstance(value, list):
            value = pick_option(q["options"], value) or value
        try:
            err = fill_field(page, q, value, files)
        except Exception as e:
            err = type(e).__name__
        if err and err.startswith("guess:"):
            problems.append(f"“{q['label'][:50]}”：{err[6:].strip()}")  # filled, but worth a look
        elif err:
            problems.append(f"“{q['label'][:50]}”：{err}")
            if q["required"]:
                unknown.append({**q, "step": step})
        elif source == "consent":
            log.append(f"☑️ 已同意：{q['label'][:120]}")
    return unknown, problems


def profile_me(profile) -> Path:
    return Path(getattr(profile, "me", "me"))


def save_and_continue(page) -> list[str]:
    before = current_step(page)
    _click(page, "pageFooterNextButton")
    page.wait_for_timeout(5000)
    if current_step(page) == before:
        return page_errors(page) or ["页面没有前进（可能有必填项）"]
    return []


def run(page, me: Path, url: str, profile, files: dict, extra: dict, email: str, password: str,
        company: str, max_steps: int = 10) -> dict:
    """Drive the flow up to Review. Returns {step, reached_review, unknown, problems, log}."""
    log: list[str] = []
    started = datetime.now(timezone.utc).isoformat()
    open_application(page, url)
    if not sign_in_or_create(page, me, email, password, log):
        if any("验证" in x or "verif" in x.lower() for x in log) and verify_from_gmail(page, me, company, started, log):
            open_application(page, url)
            sign_in_or_create(page, me, email, password, log)
    unknown, problems = [], []
    for _ in range(max_steps):
        step = current_step(page)
        if not step or re.search(r"review", step, re.I):
            break
        unknown, problems = fill_step(page, profile, files, extra, log)
        if unknown:
            break  # Claude / the user answers these, then we run again
        errs = save_and_continue(page)
        if errs:
            problems += errs
            break
    step = current_step(page)
    return {"step": step, "reached_review": bool(re.search(r"review", step, re.I)),
            "unknown": [{**{k: q[k] for k in ("step", "label", "kind", "options", "required")},
                         "answer_key": f"{q['step']}::{q['label']}"} for q in unknown],
            "problems": problems, "log": log}
