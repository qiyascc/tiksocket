from __future__ import annotations

DIALOG_JS = r"""() => {
  const seen = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 2 && r.height > 2 && s.visibility !== "hidden" && s.display !== "none" && +s.opacity !== 0; };
  const c = document.querySelector("canvas");
  let x = innerWidth / 2, y = innerHeight / 2;
  if (c) { const r = c.getBoundingClientRect(); if (r.width) { x = r.left + r.width * 0.12; y = r.top + r.height * 0.12; } }
  let root = document.elementFromPoint(x, y);
  const dialog = root && root.closest("[role=dialog], [aria-modal=true], [class*=modal i], [class*=Modal], [class*=captcha i], [id*=captcha i]");
  if (dialog) root = dialog;
  else { while (root && root.parentElement && root.parentElement !== document.body) {
    const r = root.getBoundingClientRect(); if (r.width >= 280 && r.height >= 180) break; root = root.parentElement; } }
  if (!root) return null;
  const html = root.outerHTML.toLowerCase();
  const captcha = /captcha|secsdk|verify-bar|slide/.test(html) && !!root.querySelector("img, canvas");
  const buttons = [];
  root.querySelectorAll("button, [role=button], a[href]").forEach((el) => {
    const label = (el.innerText || el.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ");
    if (!label || !seen(el) || label.length > 60) return;
    el.setAttribute("data-ea-btn", buttons.length);
    buttons.push({ i: buttons.length, label, primary: /primary|confirm|verify|submit/i.test(String(el.className)) });
  });
  const inputs = [];
  root.querySelectorAll("input:not([type=hidden]):not([type=checkbox]):not([type=radio]), textarea").forEach((el) => {
    if (!seen(el)) return;
    el.setAttribute("data-ea-input", inputs.length);
    inputs.push({ i: inputs.length, placeholder: el.placeholder || "", size: +el.maxLength > 0 ? +el.maxLength : 0, kind: el.type || "text" });
  });
  const skip = new Set(buttons.map((b) => b.label));
  const head = root.querySelector("h1, h2, h3, [class*=title i]");
  const title = head ? head.innerText.trim().slice(0, 140) : "";
  const bare = (t) => [...skip].reduce((acc, label) => acc.split(label).join(""), t).trim();
  const lines = [...new Set((root.innerText || "").split("\n").map((t) => t.trim()).filter((t) => t && t !== title && bare(t)))].slice(0, 8);
  return { title: title || (lines[0] || ""), lines: (title ? lines : lines.slice(1)).map((t) => t.slice(0, 240)),
           buttons: buttons.slice(0, 8), inputs: inputs.slice(0, 8), captcha };
}"""

COVERED_JS = """() => {
  const c = document.querySelector("canvas");
  if (!c) return document.body.innerText.trim().length > 0;
  const r = c.getBoundingClientRect();
  if (!r.width || !r.height) return true;
  const spots = [[0.12, 0.12], [0.88, 0.12], [0.12, 0.88]];
  return spots.some(([x, y]) => {
    const el = document.elementFromPoint(r.left + r.width * x, r.top + r.height * y);
    return !(el === c || (el && el.contains(c)));
  });
}"""

PRESS_JS = """
({labels, scoped}) => {
  const norm = (v) => String(v || "").trim().replace(/\\s+/g, " ").toLowerCase();
  const names = labels.map(norm).filter(Boolean);
  const matches = (text) => names.includes(text) || names.filter((n) => n !== "post").some((n) => text.includes(n));
  const root = scoped
    ? [...document.querySelectorAll("[role='dialog'], [aria-modal='true'], [class*='modal' i], [class*='dialog' i], [class*='popover' i]")]
    : [document];
  const nav = "nav, aside, [role='navigation'], [role='menu'], [class*='sidebar' i], [class*='side-nav' i], [class*='sidenav' i], [class*='menu' i]";
  const bad = /\\/(post|posts|analytics|comment|home|inspiration|monetization|academy|sound|feedback)(\\/|$|\\?)/i;
  const found = [];
  for (const box of root) {
    for (const el of box.querySelectorAll("button, [role='button']")) {
      const text = norm(el.textContent || el.getAttribute("aria-label"));
      if (!text || text === "posts" || !matches(text)) continue;
      if (el.disabled || el.getAttribute("aria-disabled") === "true") continue;
      if (!scoped && el.closest(nav)) continue;
      const a = el.closest("a");
      if (a && bad.test(norm(a.getAttribute("href")))) continue;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      const edge = window.innerWidth >= 900 ? Math.min(300, window.innerWidth * 0.25) : 0;
      if (!scoped && window.innerWidth >= 900 && r.right <= edge) continue;
      const cls = norm(el.className || "");
      const cue = /\\b(post|publish|submit|primary)\\b/.test(cls);
      if (!scoped && text === "post" && window.innerHeight >= 600 && r.top < window.innerHeight * 0.5 && !cue) continue;
      let score = 0;
      if (names.includes(text)) score += 30;
      if (el.tagName.toLowerCase() === "button") score += 20;
      if (norm(el.getAttribute("type")) === "submit") score += 20;
      if (cue) score += 20;
      if (r.width >= 80 && r.height >= 28) score += 15;
      if (r.top >= window.innerHeight * 0.5) score += 60;
      if (window.innerWidth >= 900 && r.left >= edge) score += 20;
      score += Math.min(20, Math.max(0, r.top / 40));
      found.push({ el, score, top: r.top });
    }
  }
  found.sort((x, y) => y.score - x.score || y.top - x.top);
  if (!found.length) return false;
  found[0].el.scrollIntoView({ block: "center" });
  found[0].el.click();
  return true;
}
"""

CHATS_JS = """() => [...document.querySelectorAll('[data-e2e=dm-new-conversation-item], [data-conv-id]')].map(e => ({
  id: e.dataset.convId || '',
  name: (e.querySelector('[data-e2e=dm-new-conversation-nickname]') || {}).innerText || '',
  rest: e.innerText,
  unread: !!e.querySelector('[class*=Unread], [class*=unread], [class*=Badge], [class*=badge]'),
  avatar: ((e.querySelector('[data-e2e=dm-new-conversation-avatar] img') || {}).src) || ''
}))"""

ITEMS_JS = """() => {
  const head = document.querySelector('[data-e2e=chat-uniqueid]');
  const list = document.querySelector('[data-e2e=dm-new-message-list]') || document;
  const out = [];
  let stamp = '';
  list.querySelectorAll('[data-e2e=dm-new-time-separator], [data-e2e=dm-new-chat-item]').forEach((el) => {
    if (el.dataset.e2e === 'dm-new-time-separator') { stamp = el.innerText.trim(); return; }
    const wrap = el.closest('[data-index]');
    const link = el.querySelector('a[href^="/@"]');
    const video = el.querySelector('[data-e2e=dm-new-shared-video]');
    const style = video ? (video.style.backgroundImage || '') : '';
    const thumb = (style.match(/url\\(["']?(.*?)["']?\\)/) || [])[1] || '';
    const imgs = [...el.querySelectorAll('img')].map((i) => i.src).filter((s) => s && !s.includes('-avt-'));
    const sticker = !!el.querySelector('[data-e2e*=sticker], [class*=Sticker], [class*=sticker]');
    const more = el.querySelector('[id^=more-action-icon-msg-]');
    const warn = el.querySelector('[data-e2e=dm-warning]');
    const bubble = el.cloneNode(true);
    bubble.querySelectorAll('[data-e2e=dm-new-shared-video] *, [data-area=Actions] > a').forEach((n) => n.remove());
    out.push({id: wrap ? wrap.dataset.index : '', author: link ? link.getAttribute('href') : '', stamp,
      text: (video ? el.innerText : bubble.innerText).trim().slice(0, 4000), video: !!video, thumb, imgs, sticker,
      server: more ? more.id : '', warning: warn ? warn.innerHTML.trim().slice(0, 200) : ''});
  });
  const tip = document.querySelector('[data-e2e=dm-new-request-tip]');
  const box = document.querySelector('[data-e2e=dm-new-chatbox]');
  const tail = box ? box.innerText.slice(-600) : '';
  return {handle: head ? head.innerText : '', items: out, notice: [tip ? tip.innerText.trim() : '', tail].join('\\n')};
}"""

SCROLL_JS = """(conv) => {
  const box = document.querySelector('[data-e2e=dm-new-conversation-list]');
  if (!box) return false;
  const scroller = [box, ...box.querySelectorAll('*')].find((n) => n.scrollHeight > n.clientHeight + 10) || box;
  const before = scroller.scrollTop;
  scroller.scrollTop = before + scroller.clientHeight;
  return scroller.scrollTop !== before;
}"""
