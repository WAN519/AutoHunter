// AutoHunter bookmarklet body: fill the CURRENT page of an application form from answers
// AutoHunter copied to the clipboard. Runs only when the user clicks the bookmark, in their
// own browser. Never clicks Next / Submit, never touches signature or file fields.
(async () => {
  const toast = (html, ms = 6000) => {
    let t = document.getElementById('ah-toast');
    if (!t) { t = document.createElement('div'); t.id = 'ah-toast'; document.documentElement.appendChild(t); }
    t.style.cssText = 'position:fixed;top:14px;right:14px;z-index:2147483647;max-width:340px;background:#1d1d1f;color:#fff;' +
      'font:13px/1.45 -apple-system,sans-serif;padding:10px 14px;border-radius:10px;box-shadow:0 6px 20px rgba(0,0,0,.3)';
    t.innerHTML = html; clearTimeout(t._h); t._h = setTimeout(() => t.remove(), ms);
  };
  let data;
  try { data = JSON.parse(await navigator.clipboard.readText()); } catch (e) { data = null; }
  if (!data || !data.autohunter) {
    toast('AutoHunter：剪贴板里没有填表数据。<br>先在答案小抄页点「复制填表数据」，再点这个书签。');
    return;
  }
  const norm = s => (s || '').toLowerCase().replace(/[*✱]/g, '').replace(/\s+/g, ' ').trim();
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const answers = new Map(data.answers.map(a => [norm(a.label), a]));
  const labelOf = e => {
    if (e.id) { const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`); if (l) return l.innerText; }
    const ids = e.getAttribute('aria-labelledby');
    if (ids) return ids.split(/\s+/).map(i => (document.getElementById(i) || {}).innerText || '').join(' ');
    const fs = e.closest('fieldset'); if (fs && fs.querySelector('legend')) return fs.querySelector('legend').innerText;
    const item = e.closest('[class*="form-item"], [class*="field"], [class*="question"]');
    const l = item && item.querySelector('label, legend'); return l ? l.innerText : (e.getAttribute('aria-label') || '');
  };
  const setNative = (el, v) => {  // React / Vue keep their own value: use the native setter + events
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    el.dispatchEvent(new Event('blur', {bubbles: true}));
  };
  const SIGN = /^(legal name|full legal name|signature|electronic signature|e-?signature)$/i;
  let filled = 0; const skipped = [], manual = [];
  const groups = new Set();
  for (const el of document.querySelectorAll('input, textarea, select')) {
    if (el.type === 'hidden' || el.disabled || el.closest('#ah-toast')) continue;
    if ((el.type === 'radio' || el.type === 'checkbox')) {
      const key = el.name || el.id; if (groups.has(key)) continue; groups.add(key);
      const box = el.closest('fieldset, [class*="form-item"], [class*="question"]') || el.parentElement;
      const opts = [...document.querySelectorAll(el.name ? `input[name="${CSS.escape(el.name)}"]` : `#${CSS.escape(el.id)}`)];
      const optLabel = o => norm((document.querySelector(`label[for="${CSS.escape(o.id)}"]`) || o.parentElement).innerText);
      // The question = the first title-like element in the group that isn't one of the options' labels.
      const isOpt = c => opts.some(o => c.contains(o) || (c.htmlFor && c.htmlFor === o.id) ||
                                        [...c.querySelectorAll('label[for]')].some(l => l.htmlFor === o.id));
      let title = '';
      for (let a = opts[0].parentElement, i = 0; a && i < 6 && !title; a = a.parentElement, i++) {
        const c = [...a.querySelectorAll('legend, label, [class*="label"]')].find(c => !isOpt(c) && (c.innerText || '').trim());
        if (c) title = c.innerText;
      }
      const q = norm(opts.length > 1 ? title : (title || labelOf(opts[0])));
      let a = opts.length === 1 ? answers.get(optLabel(opts[0])) : null;  // single box: its own text first
      if (!a) a = answers.get(q);
      if (!a) { for (const [k, v] of answers) if (k && q.includes(k)) { a = v; break; } }
      if (!a) continue;
      const want = norm(a.value).split(/\s*,\s*/);
      for (const o of opts) {
        const ol = optLabel(o);
        const hit = opts.length === 1 || want.some(w => w && (ol === w || ol.startsWith(w)));
        if (hit && !o.checked) { (document.querySelector(`label[for="${CSS.escape(o.id)}"]`) || o).click(); filled++; }
      }
      continue;
    }
    if (!vis(el) || el.type === 'file') { if (el.type === 'file' && vis(el.closest('label') || el.parentElement)) manual.push('上传简历：' + (data.resume || '')); continue; }
    const q = norm(labelOf(el));
    if (SIGN.test(q)) { manual.push('✍️ 电子签名：请你自己输入法定姓名'); continue; }
    const a = answers.get(q);
    if (!a) continue;
    if (el.value && norm(el.value) === norm(a.value)) continue;
    if (el.readOnly) { skipped.push(`${labelOf(el).trim().slice(0, 40)} → ${a.value}（日历选择，请手动点）`); continue; }
    if (el.tagName === 'SELECT') {
      const opt = [...el.options].find(o => norm(o.text) === norm(a.value)) || [...el.options].find(o => norm(o.text).startsWith(norm(a.value)));
      if (opt) { setNative(el, opt.value); filled++; } else skipped.push(`${labelOf(el).trim().slice(0, 40)} → ${a.value}`);
      continue;
    }
    setNative(el, a.value); filled++;
  }
  const extra = [...new Set(manual)].concat(skipped);
  toast(`AutoHunter：这一页填了 <b>${filled}</b> 项。` +
        (extra.length ? `<br>还需要你：<ul style="margin:4px 0 0;padding-left:18px">${extra.map(x => `<li>${x}</li>`).join('')}</ul>` : '') +
        '<br>检查后点 Next；下一页再点一次书签。', 12000);
})();
