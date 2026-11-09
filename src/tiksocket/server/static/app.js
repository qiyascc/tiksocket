(() => {
  const $ = (s) => document.querySelector(s);
  const params = new URLSearchParams(location.search);
  let token = params.get("token") || localStorage.getItem("tiksocket-token") || "";
  if (params.get("token")) { localStorage.setItem("tiksocket-token", token); history.replaceState(null, "", "/"); }
  let account = localStorage.getItem("tiksocket-account") || "default";
  let chat = "";
  let poller = 0;

  const api = async (path, options = {}) => {
    const headers = { Authorization: `Bearer ${token}`, ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}) };
    const res = await fetch(`/api/accounts/${encodeURIComponent(account)}${path}`, { ...options, headers });
    if (res.status === 401) {
      token = prompt("API token (printed by tiksocket serve)") || "";
      localStorage.setItem("tiksocket-token", token);
      return api(path, options);
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.message || data.error || res.statusText);
    return data;
  };
  const show = (id) => ["login-idle", "login-qr", "login-verify", "login-open"].forEach((x) => { $("#" + x).hidden = x !== id; });
  const fail = (el, err) => { el.textContent = err ? String(err.message || err) : ""; el.hidden = !err; };

  const loadAccounts = async () => {
    const res = await fetch("/api/accounts", { headers: { Authorization: `Bearer ${token}` } });
    const data = res.ok ? await res.json() : { accounts: [] };
    const names = new Set([account, ...data.accounts.map((a) => a.account)]);
    $("#account").replaceChildren(...[...names].map((n) => new Option(n, n, false, n === account)));
  };

  const render = (view) => {
    fail($("#login-error"), null);
    if (view.state === "open" || (view.profile && view.state !== "qr" && view.state !== "verify")) {
      show("login-open");
      $("#me").textContent = view.profile ? `@${view.profile.username}` : "";
      $("#who").textContent = view.profile ? `@${view.profile.username}` : "";
      clearInterval(poller);
      return;
    }
    if (view.state === "qr" && view.qr) {
      show("login-qr");
      $("#qr-img").src = view.qr.image;
      $("#qr-status").textContent = view.status ? `Status: ${view.status}` : "Waiting for scan";
      return;
    }
    if (view.state === "verify" && view.prompt) {
      show("login-verify");
      const p = view.prompt;
      $("#v-title").textContent = p.title || "TikTok wants to confirm the login";
      $("#v-lines").replaceChildren(...(p.lines || []).map((t) => Object.assign(document.createElement("p"), { textContent: t })));
      $("#v-code").hidden = !p.needs_code;
      $("#v-buttons").replaceChildren(...(p.buttons || []).filter((b) => !(p.needs_code && b.primary)).map((b) => {
        const btn = Object.assign(document.createElement("button"), { type: "button", textContent: b.label, className: b.primary ? "" : "ghost" });
        btn.onclick = () => act("/login/press", { index: b.i });
        return btn;
      }));
      $("#v-shot").hidden = !p.has_screenshot;
      if (p.has_screenshot) $("#v-img").src = `/api/accounts/${encodeURIComponent(account)}/login/screenshot?token=${encodeURIComponent(token)}&t=${Date.now()}`;
      return;
    }
    show("login-idle");
  };

  const refresh = async () => { try { render(await api("/login")); } catch (e) { fail($("#login-error"), e); } };
  const act = async (path, body) => { try { render(await api(path, { method: "POST", body: JSON.stringify(body) })); } catch (e) { fail($("#login-error"), e); } };

  $("#qr-start").onclick = async () => {
    $("#qr-start").disabled = true;
    try { render(await api("/login/qr", { method: "POST" })); clearInterval(poller); poller = setInterval(refresh, 2500); }
    catch (e) { fail($("#login-error"), e); }
    $("#qr-start").disabled = false;
  };
  $("#cookie-go").onclick = () => act("/login/cookie", { cookie: $("#cookie").value }).then(refresh);
  $("#logout").onclick = async () => { await api("/session", { method: "DELETE" }); $("#who").textContent = ""; refresh(); };
  $("#v-code").onsubmit = (e) => { e.preventDefault(); act("/login/code", { code: e.target.code.value }); e.target.code.value = ""; };
  let start = null;
  const spot = (e) => { const r = $("#v-img").getBoundingClientRect(); return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }; };
  $("#v-img").addEventListener("pointerdown", (e) => { e.preventDefault(); start = spot(e); });
  $("#v-img").addEventListener("pointerup", async (e) => {
    if (!start) return;
    const end = spot(e);
    const body = Math.hypot(end.x - start.x, end.y - start.y) > 0.015 ? { x: start.x, y: start.y, x2: end.x, y2: end.y } : start;
    start = null;
    await api("/login/tap", { method: "POST", body: JSON.stringify(body) }).catch((err) => fail($("#login-error"), err));
    refresh();
  });

  $("#post").onsubmit = async (e) => {
    e.preventDefault();
    const form = e.target;
    const data = new FormData();
    const kind = form.kind.value;
    data.append("kind", kind);
    for (const name of ["caption", "title", "sound"]) data.append(name, form[name].value);
    data.append("auto_sound", form.auto_sound.checked ? "1" : "0");
    data.append("dry_run", form.dry_run.checked ? "1" : "0");
    [...form.files.files].forEach((f) => data.append("file", f, f.name));
    $("#post-result").textContent = "Uploading, this can take a few minutes...";
    form.querySelector("button").disabled = true;
    try {
      const res = await api("/posts", { method: "POST", body: data });
      $("#post-result").textContent = res.url ? `Posted: ${res.url}` : `Done${res.sound ? `, sound: ${res.sound}` : ""}`;
    } catch (err) { $("#post-result").textContent = `Error: ${err.message}`; }
    form.querySelector("button").disabled = false;
  };

  const loadChats = async () => {
    try {
      const { chats } = await api("/chats");
      $("#chats").replaceChildren(...chats.map((c) => {
        const li = document.createElement("li");
        li.className = c.id === chat ? "on" : "";
        li.append(Object.assign(document.createElement("b"), { textContent: c.name }), Object.assign(document.createElement("small"), { textContent: `${c.date} ${c.preview}` }));
        li.onclick = () => openChat(c);
        return li;
      }));
    } catch (e) { $("#thread-head").textContent = e.message; }
  };
  const openChat = async (c) => {
    chat = c.id;
    $("#thread-head").textContent = c.name;
    $("#send").hidden = false;
    const { messages } = await api(`/chats/${encodeURIComponent(c.id)}/messages`);
    $("#messages").replaceChildren(...messages.map((m) => {
      const li = document.createElement("li");
      li.className = m.from_me ? "me" : "";
      if (m.image || m.thumb) li.append(Object.assign(document.createElement("img"), { src: m.image || m.thumb, alt: m.kind }));
      if (m.text) li.append(document.createTextNode(m.text));
      if (!m.text && !m.image && !m.thumb) li.textContent = `[${m.kind}]`;
      return li;
    }));
    $("#messages").scrollTop = $("#messages").scrollHeight;
    loadChats();
  };
  $("#reload-chats").onclick = loadChats;
  $("#send").onsubmit = async (e) => {
    e.preventDefault();
    const text = e.target.text.value.trim();
    if (!text || !chat) return;
    fail($("#send-error"), null);
    try {
      await api(`/chats/${encodeURIComponent(chat)}/messages`, { method: "POST", body: JSON.stringify({ text, client_id: crypto.randomUUID() }) });
      e.target.text.value = "";
      openChat({ id: chat, name: $("#thread-head").textContent });
    } catch (err) { fail($("#send-error"), err); }
  };

  const stream = () => {
    const es = new EventSource(`/api/events?token=${encodeURIComponent(token)}`);
    es.onopen = () => $("#live").classList.add("on");
    es.onerror = () => $("#live").classList.remove("on");
    es.onmessage = (e) => {
      const item = JSON.parse(e.data);
      const li = document.createElement("li");
      li.textContent = `${new Date().toLocaleTimeString()} ${item.account} ${item.event} ${JSON.stringify(item.data).slice(0, 300)}`;
      $("#events").prepend(li);
      if (item.account === account && ["qr", "verify", "connection.update", "qr.status"].includes(item.event)) refresh();
      if (item.account === account && item.event === "messages.upsert") { loadChats(); if (item.data.chat && item.data.chat.id === chat) openChat(item.data.chat); }
    };
  };

  $("#account").onchange = (e) => { account = e.target.value; localStorage.setItem("tiksocket-account", account); chat = ""; refresh(); };
  $("#add").onclick = () => {
    const name = (prompt("Account name (letters, digits, dot, dash)") || "").trim();
    if (!name) return;
    account = name;
    localStorage.setItem("tiksocket-account", account);
    loadAccounts().then(refresh);
  };

  loadAccounts().then(refresh);
  stream();
})();
