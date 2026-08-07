/* tangyuanAI landing page — minimal interactions
   模块化版本：initLanding(rootEl) 负责初始化，返回 cleanup 函数供卸载时调用。 */
export function initLanding(rootEl) {
  const $  = (s, ctx = rootEl) => ctx.querySelector(s);
  const $$ = (s, ctx = rootEl) => [...ctx.querySelectorAll(s)];

  const listeners = [];
  let io = null;
  let toastTimer = null;
  let starAbort = null;

  /* ── Stagger: assign per-group delay (120ms steps, capped) ── */
  const reveals = $$(".reveal");
  reveals.forEach((el) => {
    const siblings = $$(".reveal", el.parentElement);
    const idx = siblings.indexOf(el);
    el.style.setProperty("--d", Math.min(idx * 120, 720) + "ms");
  });

  /* ── Scroll reveal ─────────────────────────────────────── */
  if ("IntersectionObserver" in window) {
    io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          e.target.classList.add("in");
          io.unobserve(e.target);
        }
      });
    }, { threshold: 0.15, rootMargin: "0px 0px -8% 0px" });
    reveals.forEach((el) => io.observe(el));
  } else {
    reveals.forEach((el) => el.classList.add("in"));
  }

  /* ── Copy to clipboard ─────────────────────────────────── */
  const toast = $("#toast");
  const showToast = () => {
    if (!toast) return;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 1800);
  };

  const targetText = (sel) => {
    const node = rootEl.querySelector(sel);
    if (!node) return "";
    return node.innerText.trim();
  };

  $$("[data-copy]").forEach((btn) => {
    const handler = async () => {
      const val = btn.getAttribute("data-copy");
      const text = val && val.startsWith("#") ? targetText(val) : (val || "");
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      showToast();
    };
    btn.addEventListener("click", handler);
    listeners.push([btn, "click", handler]);
  });

  /* ── GitHub stars (non-blocking) ───────────────────────── */
  const starBadge = $("#starCount");
  if (starBadge) {
    starAbort = new AbortController();
    const fmt = (n) => (n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(n));
    fetch("https://api.github.com/repos/secret-tangyuan/tangyuanAI", { signal: starAbort.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => { starBadge.textContent = fmt(d.stargazers_count || 0); })
      .catch(() => { /* keep ★ fallback */ });
  }

  /* ── Cleanup ───────────────────────────────────────────── */
  return function destroy() {
    listeners.forEach(([el, type, fn]) => el.removeEventListener(type, fn));
    if (io) io.disconnect();
    if (starAbort) starAbort.abort();
    clearTimeout(toastTimer);
  };
}