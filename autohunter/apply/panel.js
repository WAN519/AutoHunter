(data) => {
  // AutoHunter review panel. Lives in a Shadow DOM so the page's CSS can't touch it (and it
  // can't touch the page). It is never part of the submitted form.
  document.getElementById('autohunter-panel')?.remove();
  const host = document.createElement('div');
  host.id = 'autohunter-panel';
  host.style.cssText = 'position:fixed;top:16px;right:16px;z-index:2147483647';
  const s = host.attachShadow({mode: 'open'});
  const esc = t => String(t ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const li = a => (a || []).map(x => `<li>${esc(x)}</li>`).join('');
  const letter = data.letter ? `<div class="m">${esc(data.letter)}</div>` : `<div class="m">—（没写）</div>`;
  const warn = data.warn?.length ? `<div class="r"><b>⛔ 注意：</b><ul>${li(data.warn)}</ul></div>` : '';
  const todo = data.todo?.length ? `<div class="w"><b>⚠️ 需要你看（${data.todo.length}）：</b><ul>${li(data.todo)}</ul></div>`
                                 : `<div class="ok">✅ 没有要你处理的项</div>`;
  const consents = data.consents?.length
    ? `<div class="g"><b>☑️ 已替你同意（${data.consents.length}）：</b><ul>${data.consents.map(c =>
        `<li>${esc(c.summary)}<div class="m">选了：${esc(c.chosen)}</div></li>`).join('')}</ul><div class="m">不同意的话，在表单里取消勾选。</div></div>` : '';
  s.innerHTML = `<style>
    .p{width:310px;max-height:85vh;overflow:auto;font:13px/1.45 -apple-system,"PingFang SC",sans-serif;background:#fff;color:#1d1d1f;
       border:1px solid #d2d2d7;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.15);padding:12px 14px}
    h3{margin:0;font-size:14px;display:inline} .m{color:#6e6e73;font-size:12px} ul{margin:4px 0 8px;padding-left:18px}
    .w{background:#fff8e1;border-radius:8px;padding:6px 10px;margin:8px 0} .r{background:#ffeceb;border-radius:8px;padding:6px 10px;margin:8px 0}
    .ok{color:#1a7f37;margin:8px 0} b{font-weight:600} .g{background:#eef6ff;border-radius:8px;padding:6px 10px;margin:8px 0}
    button{float:right;border:0;background:none;font-size:16px;cursor:pointer;color:#6e6e73;line-height:1}
    .c{width:auto;padding:6px 10px;cursor:pointer} .c .b{display:none} .badge{background:#ff9f0a;color:#fff;border-radius:9px;padding:0 6px;font-size:11px;margin-left:6px}
  </style>
  <div class="p ${data.collapsed ? 'c' : ''}"><button title="收起 / 展开">${data.collapsed ? '+' : '—'}</button>
    <h3>AutoHunter</h3>${data.todo?.length ? `<span class="badge">${data.todo.length}</span>` : ''}
    <div class="b">
      <div class="m">${esc(data.title)}${data.fit ? ' · 匹配 ' + esc(data.fit) : ''}</div>
      ${warn}${todo}${consents}
      <b>📄 简历</b><div class="m">${esc(data.resume_oneline || '')}</div><ul>${li(data.points)}</ul>
      <b>✉️ Cover letter</b>${letter}
      <div class="m" style="margin-top:8px">已填 ${data.done_count} 项。不会自动提交：确认后你自己点 Submit，提交后会自动记录。</div>
    </div></div>`;
  const p = s.querySelector('.p'), btn = s.querySelector('button');
  const toggle = () => { p.classList.toggle('c'); btn.textContent = p.classList.contains('c') ? '+' : '—'; };
  btn.onclick = e => { e.stopPropagation(); toggle(); };
  p.onclick = () => { if (p.classList.contains('c')) toggle(); };
  document.documentElement.appendChild(host);
}
