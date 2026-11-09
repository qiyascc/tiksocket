(() => {
  const SHOT_MS = 900;

  function mount(root, { api, token, onClose }) {
    root.classList.add("cap");
    root.innerHTML = `
      <div class="cap-head"><b class="cap-title">TikTok verification</b><span class="cap-timer muted"></span></div>
      <p class="muted cap-hint">This is the live TikTok page. Drag the slider or click the objects on the picture exactly as you would on TikTok.</p>
      <div class="cap-stage"><img class="cap-img" alt="" draggable="false" hidden><div class="cap-wait muted">Loading the picture...</div></div>
      <div class="row"><button type="button" class="ghost small cap-refresh">New puzzle</button><span class="cap-status muted grow"></span>${onClose ? '<button type="button" class="ghost small cap-close">Hide</button>' : ""}</div>`;
    const $ = (s) => root.querySelector(s);
    const img = $(".cap-img");
    let pending = null, timer = 0, busy = false, stopped = false;

    const call = async (path, body) => {
      const res = await fetch(`${api}${path}`, {
        method: body ? "POST" : "GET",
        headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).message || res.statusText);
      return res.json();
    };
    const status = (text) => { $(".cap-status").textContent = text || ""; };
    const shot = () => new Promise((resolve) => {
      const next = new Image();
      next.onload = () => { img.src = next.src; img.hidden = false; $(".cap-wait").hidden = true; resolve(); };
      next.onerror = () => resolve();
      next.src = `${api}/captcha/image?token=${encodeURIComponent(token)}&t=${Date.now()}`;
    });
    const tick = async () => {
      if (stopped) return;
      try {
        const { pending: now } = await call("/captcha");
        if (!now) {
          const was = pending;
          pending = null;
          status(was ? "Solved, TikTok continues." : "No captcha is waiting right now.");
          img.hidden = true;
          img.removeAttribute("src");
          $(".cap-wait").hidden = false;
          $(".cap-wait").textContent = was ? "Solved" : "Nothing to solve.";
          if (was && onClose) setTimeout(() => onClose(true), 1200);
        } else {
          pending = now;
          $(".cap-title").textContent = now.title || "TikTok verification";
          const left = Math.max(0, Math.round(now.expires - Date.now() / 1000));
          $(".cap-timer").textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} left`;
          if (!busy) await shot();
        }
      } catch (e) { status(e.message); }
      timer = setTimeout(tick, SHOT_MS);
    };

    const point = (e) => {
      const r = img.getBoundingClientRect();
      return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
    };
    let path = null, last = 0;
    img.addEventListener("pointerdown", (e) => {
      if (!pending) return;
      e.preventDefault();
      img.setPointerCapture(e.pointerId);
      busy = true; last = performance.now();
      path = [[...point(e), 0]];
    });
    img.addEventListener("pointermove", (e) => {
      if (!path) return;
      const now = performance.now();
      if (now - last < 12) return;
      path.push([...point(e), Math.round(now - last)]);
      last = now;
    });
    const finish = async (e) => {
      if (!path) return;
      path.push([...point(e), Math.round(performance.now() - last)]);
      const moved = Math.hypot(path[path.length - 1][0] - path[0][0], path[path.length - 1][1] - path[0][1]);
      const sent = path; path = null;
      try {
        if (moved < 0.01) { status("Click sent"); await call("/captcha/tap", { x: sent[0][0], y: sent[0][1] }); }
        else { status("Drag sent"); await call("/captcha/drag", { path: sent }); }
      } catch (err) { status(err.message); }
      busy = false;
      setTimeout(shot, 500);
    };
    img.addEventListener("pointerup", finish);
    img.addEventListener("pointercancel", () => { path = null; busy = false; });
    $(".cap-refresh").onclick = async () => {
      try { const r = await call("/captcha/refresh", {}); status(r.ok ? "New puzzle requested" : "No refresh button on this captcha"); } catch (e) { status(e.message); }
      setTimeout(shot, 800);
    };
    if ($(".cap-close")) $(".cap-close").onclick = () => onClose && onClose(false);
    tick();
    return { stop() { stopped = true; clearTimeout(timer); } };
  }

  window.TikCaptcha = { mount };
})();
