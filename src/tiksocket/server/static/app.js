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

  const el = (tag, props = {}, ...kids) => { const n = Object.assign(document.createElement(tag), props); n.append(...kids); return n; };
  const num = (n) => Intl.NumberFormat("en", { notation: "compact" }).format(n || 0);
  const busy = async (button, work) => { if (button) button.disabled = true; try { return await work(); } finally { if (button) button.disabled = false; } };
  let person = "";
  let postRef = "";
  const userRow = (u) => el("li", {}, u.avatar ? el("img", { src: u.avatar, alt: "" }) : "",
    el("div", { className: "grow" }, el("b", { textContent: `@${u.username}` }), el("small", { textContent: `${u.nickname} · ${num(u.followers)} followers` })),
    el("button", { type: "button", className: "ghost small", textContent: "Open", onclick: () => openPerson(u.username) }));
  const postRow = (p) => el("li", {}, p.cover ? el("img", { src: p.cover, alt: "" }) : "",
    el("div", { className: "grow" }, el("b", { textContent: `@${p.author} · ${p.kind}` }), el("small", { textContent: `${num(p.likes)} likes · ${num(p.comments)} comments · ${p.caption}` })),
    el("button", { type: "button", className: "ghost small", textContent: "Open", onclick: () => openPost(p.url || p.id) }));

  const openPerson = async (name) => {
    fail($("#people-error"), null);
    try {
      const u = await api(`/users/${encodeURIComponent(name)}`);
      person = u.username;
      $("#person").hidden = $("#person-actions").hidden = $("#dm-new").hidden = false;
      $("#p-avatar").src = u.avatar || "";
      $("#p-name").textContent = `${u.nickname} @${u.username}${u.verified ? " ✓" : ""}${u.private ? " (private)" : ""}`;
      $("#p-bio").textContent = u.bio || "";
      $("#p-stats").textContent = `${num(u.followers)} followers · ${num(u.following)} following · ${num(u.likes)} likes · ${u.is_following ? "you follow" : "not following"}`;
    } catch (e) { fail($("#people-error"), e); }
  };
  $("#people").onsubmit = (e) => { e.preventDefault(); openPerson(e.target.user.value); };
  $("#find-users").onsubmit = async (e) => {
    e.preventDefault();
    fail($("#people-error"), null);
    try { const page = await api(`/search/users?q=${encodeURIComponent(e.target.q.value)}`); $("#people-list").replaceChildren(...page.items.map(userRow)); }
    catch (err) { fail($("#people-error"), err); }
  };
  document.querySelectorAll("[data-user]").forEach((b) => b.onclick = () => busy(b, async () => {
    fail($("#people-error"), null);
    const [verb, action] = b.dataset.user.includes(" ") ? b.dataset.user.split(" ") : ["GET", b.dataset.user];
    if (verb === "POST" && action === "block" && !confirm(`Block @${person}?`)) return;
    try {
      const base = `/users/${encodeURIComponent(person)}`;
      if (verb === "GET" && action === "posts") { const { posts } = await api(`${base}/posts`); $("#people-list").replaceChildren(...posts.map(postRow)); return; }
      if (verb === "GET") { const page = await api(`${base}/${action}`); $("#people-list").replaceChildren(...page.items.map(userRow)); return; }
      const res = await api(`${base}/${action}`, { method: verb });
      $("#p-stats").textContent = `${res.action}: ${res.changed ? "done" : "already so"}`;
    } catch (err) { fail($("#people-error"), err); }
  }));
  $("#dm-new").onsubmit = async (e) => {
    e.preventDefault();
    fail($("#people-error"), null);
    try {
      const res = await api("/chats", { method: "POST", body: JSON.stringify({ username: person, text: e.target.text.value, client_id: crypto.randomUUID() }) });
      e.target.text.value = "";
      $("#p-stats").textContent = `Sent${res.chat_id ? `, chat ${res.chat_id}` : ""}`;
      loadChats();
    } catch (err) { fail($("#people-error"), err); }
  };

  const openPost = async (ref) => {
    fail($("#post-error"), null);
    try {
      const p = await api(`/post?post=${encodeURIComponent(ref)}`);
      postRef = p.url || ref;
      $("#post-ref").post.value = postRef;
      $("#post-view").hidden = $("#post-actions").hidden = $("#comment-form").hidden = false;
      $("#own-actions").hidden = !(p.author && $("#who").textContent === `@${p.author}`);
      $("#pv-cover").src = p.cover || "";
      $("#pv-author").textContent = `@${p.author} · ${p.kind}${p.private ? " · private" : ""}`;
      $("#pv-caption").textContent = p.caption;
      $("#pv-stats").textContent = `${num(p.plays)} plays · ${num(p.likes)} likes${p.liked ? " (you)" : ""} · ${num(p.comments)} comments · ${num(p.saves)} saves${p.saved ? " (you)" : ""} · ${p.music}`;
      $("#pv-download").href = `/api/accounts/${encodeURIComponent(account)}/post/download?post=${encodeURIComponent(postRef)}&token=${encodeURIComponent(token)}`;
    } catch (e) { fail($("#post-error"), e); }
  };
  $("#post-ref").onsubmit = (e) => { e.preventDefault(); openPost(e.target.post.value); };
  const loadComments = async () => {
    const { comments } = await api(`/post/comments?post=${encodeURIComponent(postRef)}`);
    $("#comment-list").replaceChildren(...comments.map((c) => el("li", {},
      el("div", { className: "grow" }, el("b", { textContent: `@${c.author}` }), el("small", { textContent: `${c.text} · ${num(c.likes)} likes` })),
      el("button", { type: "button", className: "ghost small", textContent: "Reply", onclick: () => { $("#comment-form").reply.value = c.id; $("#comment-form").text.placeholder = `Reply to @${c.author}`; $("#comment-form").text.focus(); } }),
      el("button", { type: "button", className: "ghost small", textContent: "Like", onclick: (ev) => busy(ev.target, () => postAct("like-comment", { comment_id: c.id })) }),
      c.author && $("#who").textContent === `@${c.author}` ? el("button", { type: "button", className: "ghost small", textContent: "Delete", onclick: (ev) => busy(ev.target, () => postAct("delete-comment", { comment_id: c.id }).then(loadComments)) }) : "")));
  };
  const postAct = async (action, extra = {}) => {
    fail($("#post-error"), null);
    try {
      const res = await api(`/post/${action}`, { method: "POST", body: JSON.stringify({ post: postRef, ...extra }) });
      $("#pv-stats").textContent = res.action ? `${res.action}: ${res.changed === false ? "already so" : "done"}` : "Done";
      return res;
    } catch (err) { fail($("#post-error"), err); return null; }
  };
  document.querySelectorAll("[data-post]").forEach((b) => b.onclick = () => busy(b, async () => {
    const action = b.dataset.post;
    if (action === "comments") { await loadComments().catch((err) => fail($("#post-error"), err)); return; }
    if (action === "delete" && !confirm("Delete this post for good?")) return;
    if (action === "settings") {
      const who = $("#pv-who").value;
      const comments = $("#pv-comments").value;
      await postAct("settings", { who_can_view: who, ...(comments ? { comments: comments === "1" } : {}) });
      return;
    }
    await postAct(action);
  }));
  $("#comment-form").onsubmit = async (e) => {
    e.preventDefault();
    const form = e.target;
    const text = form.text.value.trim();
    if (!text) return;
    const res = await postAct(form.reply.value ? "reply" : "comment", { text, comment_id: form.reply.value });
    if (res) { form.text.value = ""; form.reply.value = ""; form.text.placeholder = "Write a comment"; loadComments().catch(() => {}); }
  };

  $("#profile").onsubmit = async (e) => {
    e.preventDefault();
    const form = e.target;
    const body = {};
    for (const name of ["name", "username", "bio"]) if (form[name].value.trim()) body[name] = form[name].value.trim();
    const file = form.avatar.files[0];
    if (file) body.avatar = await new Promise((ok) => { const r = new FileReader(); r.onload = () => ok(r.result); r.readAsDataURL(file); });
    if (!Object.keys(body).length) { $("#profile-result").textContent = "Nothing to change"; return; }
    $("#profile-result").textContent = "Saving...";
    try { const u = await api("/profile", { method: "PATCH", body: JSON.stringify(body) }); $("#profile-result").textContent = `Saved: @${u.username} ${u.nickname}`; refresh(); }
    catch (err) { $("#profile-result").textContent = `Error: ${err.message}`; }
  };
  const privacy = (value) => async (e) => busy(e.target, async () => {
    try { const res = await api("/privacy", { method: "POST", body: JSON.stringify({ private: value }) }); $("#profile-result").textContent = `Account is ${value ? "private" : "public"}${res.changed ? "" : " already"}`; }
    catch (err) { $("#profile-result").textContent = `Error: ${err.message}`; }
  });
  $("#go-private").onclick = privacy(true);
  $("#go-public").onclick = privacy(false);

  const explore = async (work) => { fail($("#explore-error"), null); try { await work(); } catch (err) { fail($("#explore-error"), err); } };
  document.querySelectorAll("[data-feed]").forEach((b) => b.onclick = () => busy(b, () => explore(async () => {
    const { posts } = await api(`/feed?kind=${b.dataset.feed}&count=12`);
    $("#explore-list").replaceChildren(...posts.map(postRow));
  })));
  $("#find-posts").onsubmit = (e) => { e.preventDefault(); explore(async () => {
    const q = e.target.q.value.trim();
    if (q.startsWith("#")) {
      const res = await api(`/hashtags/${encodeURIComponent(q.slice(1))}?posts=20`);
      $("#explore-list").replaceChildren(el("li", {}, el("b", { textContent: `#${res.hashtag.name} · ${num(res.hashtag.views)} views` })), ...res.posts.map(postRow));
      return;
    }
    const page = await api(`/search/posts?q=${encodeURIComponent(q)}`);
    $("#explore-list").replaceChildren(...page.items.map(postRow));
  }); };
  $("#load-notices").onclick = (e) => busy(e.target, () => explore(async () => {
    const { notifications } = await api("/notifications?count=30");
    $("#explore-list").replaceChildren(...notifications.map((n) => el("li", {}, el("div", { className: "grow" },
      el("b", { textContent: `${n.kind} · ${n.users.map((u) => "@" + u).join(", ")}` }),
      el("small", { textContent: `${new Date(n.created * 1000).toLocaleString()} ${n.text}` })))));
  }));
  $("#load-requests").onclick = (e) => busy(e.target, () => explore(async () => {
    const { requests } = await api("/requests");
    $("#explore-list").replaceChildren(...requests.map((r) => el("li", {}, el("div", { className: "grow" }, el("b", { textContent: r.name }), el("small", { textContent: r.preview })),
      el("button", { type: "button", className: "small", textContent: "Accept", onclick: (ev) => busy(ev.target, () => explore(() => api(`/requests/${encodeURIComponent(r.id)}`, { method: "POST" }).then(() => $("#load-requests").click()))) }),
      el("button", { type: "button", className: "ghost small", textContent: "Delete", onclick: (ev) => busy(ev.target, () => explore(() => api(`/requests/${encodeURIComponent(r.id)}`, { method: "DELETE" }).then(() => $("#load-requests").click()))) }))));
  }));

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
