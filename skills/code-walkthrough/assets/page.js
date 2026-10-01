(function () {
  const NS = "http://www.w3.org/2000/svg";
  const narrow = window.matchMedia("(max-width: 1000px)");

  function layout(cw) {
    const svg = cw.querySelector(".wires");
    svg.replaceChildren();
    if (narrow.matches || !cw.offsetParent) return;
    const code = cw.querySelector(".code");
    const notesCol = cw.querySelector(".notes");
    const wrapBox = cw.getBoundingClientRect();
    let floor = 0;
    cw.querySelectorAll(".note").forEach((note) => {
      const row = code.querySelector('.ln[data-n="' + note.dataset.line + '"]');
      if (!row) return;
      const rowTop = row.offsetTop;
      const top = Math.max(rowTop - 4, floor);
      note.style.top = top + "px";
      floor = top + note.offsetHeight + 8;

      const text = row.querySelector(".tx");
      const codeBox = code.getBoundingClientRect();
      const textBox = text.getBoundingClientRect();
      const rowMid = row.getBoundingClientRect().top - wrapBox.top + row.offsetHeight / 2;
      let x1 = Math.min(textBox.right, codeBox.right - 6) - wrapBox.left + 8;
      const x2 = notesCol.offsetLeft + 22;
      const y2 = top + 14;
      if (x1 > x2 - 30) x1 = x2 - 30;
      const mid = (x1 + x2) / 2;
      const path = document.createElementNS(NS, "path");
      path.setAttribute("d", `M${x1},${rowMid} C${mid},${rowMid} ${mid},${y2} ${x2 - 2},${y2}`);
      path.dataset.note = note.dataset.note;
      const dot = document.createElementNS(NS, "circle");
      dot.setAttribute("cx", x1);
      dot.setAttribute("cy", rowMid);
      dot.setAttribute("r", 3.2);
      svg.append(path, dot);
    });
    notesCol.style.minHeight = floor + "px";
  }

  function layoutVisible() {
    document.querySelectorAll(".flow:not([hidden]) .cw").forEach(layout);
  }

  function focusNote(cw, id, on) {
    cw.querySelectorAll('[data-note="' + id + '"]').forEach((el) => el.classList.toggle("on", on));
  }
  document.querySelectorAll(".cw").forEach((cw) => {
    cw.addEventListener("mouseover", (e) => {
      const el = e.target.closest("[data-note]");
      if (el) focusNote(cw, el.dataset.note, true);
    });
    cw.addEventListener("mouseout", (e) => {
      const el = e.target.closest("[data-note]");
      if (el) focusNote(cw, el.dataset.note, false);
    });
    cw.querySelector(".code").addEventListener("scroll", () => layout(cw), { passive: true });
  });

  // Old version of deleted/replaced lines: hover shows a floating preview, click opens it inline.
  const pop = document.createElement("div");
  pop.className = "delpop";
  pop.hidden = true;
  document.body.append(pop);
  const delsOf = (dm) => dm.closest(".ln").nextElementSibling;
  document.addEventListener("mouseover", (e) => {
    const dm = e.target.closest(".dm");
    if (!dm || delsOf(dm).classList.contains("open")) return;
    pop.innerHTML = delsOf(dm).outerHTML;
    pop.hidden = false;
    const r = dm.getBoundingClientRect();
    const left = Math.max(12, Math.min(r.right + 8, window.innerWidth - pop.offsetWidth - 12));
    let top = r.bottom + 6;
    if (top + pop.offsetHeight > window.innerHeight - 12) top = Math.max(12, r.top - pop.offsetHeight - 6);
    pop.style.left = left + "px";
    pop.style.top = top + "px";
  });
  document.addEventListener("mouseout", (e) => {
    if (e.target.closest(".dm")) pop.hidden = true;
  });
  document.addEventListener("click", (e) => {
    const dm = e.target.closest(".dm");
    if (!dm) return;
    const open = delsOf(dm).classList.toggle("open");
    dm.setAttribute("aria-expanded", String(open));
    pop.hidden = true;
  });
  window.addEventListener("scroll", () => (pop.hidden = true), { passive: true });

  // Execution-order rail.
  const toggle = document.querySelector(".rail-toggle");
  const currentRail = () => document.querySelector(".flow:not([hidden]) .rail");
  const wide = window.matchMedia("(min-width: 1700px)");
  let lockUntil = 0;
  function go(id) {
    const el = document.getElementById(id);
    if (!el) return;
    // Keep the scroll spy quiet until this jump has finished; scrollend where supported, else a timeout.
    lockUntil = Date.now() + 4000;
    const release = () => {
      lockUntil = 0;
      window.removeEventListener("scrollend", release);
    };
    if ("onscrollend" in window) window.addEventListener("scrollend", release);
    else setTimeout(release, 1500);
    el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    if (el.classList.contains("ln")) {
      el.classList.remove("flash");
      void el.offsetWidth;
      el.classList.add("flash");
    }
    if (!wide.matches) setRail(false);
  }
  function setRail(open) {
    const r = currentRail();
    if (r) r.classList.toggle("open", open);
    if (toggle) toggle.setAttribute("aria-expanded", String(open));
  }
  function setActive(li) {
    const r = currentRail();
    if (!r) return;
    r.querySelectorAll(".rs.active").forEach((x) => x.classList.remove("active"));
    if (li) {
      li.classList.add("active");
      const ol = r.querySelector("ol");
      const top = li.offsetTop - ol.offsetTop;
      if (top < ol.scrollTop || top > ol.scrollTop + ol.clientHeight - 40) ol.scrollTop = top - 40;
    }
  }
  function stepBy(dir) {
    const r = currentRail();
    if (!r) return;
    const items = [...r.querySelectorAll(".rs")];
    const cur = items.indexOf(r.querySelector(".rs.active"));
    const next = items[Math.max(0, Math.min(items.length - 1, cur + dir))] || items[0];
    setActive(next);
    go(next.querySelector(".rs-b").dataset.target);
  }
  document.addEventListener("click", (e) => {
    const t = e.target.closest(".rail [data-target]");
    if (t) {
      setActive(t.closest(".rs"));
      go(t.dataset.target);
      return;
    }
    const d = e.target.closest(".rail [data-dir]");
    if (d) stepBy(Number(d.dataset.dir));
  });
  if (toggle) toggle.addEventListener("click", () => setRail(!(currentRail() && currentRail().classList.contains("open"))));
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, [contenteditable]") || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "n") stepBy(1);
    else if (e.key === "p") stepBy(-1);
    else if (e.key === "Escape") setRail(false);
  });
  // Scroll spy: the active step is the one whose code line sits nearest above the reading line,
  // whatever its number — step 12 may well live in the first file.
  let spy = 0;
  window.addEventListener("scroll", () => {
    cancelAnimationFrame(spy);
    spy = requestAnimationFrame(() => {
      if (Date.now() < lockUntil) return;
      const r = currentRail();
      if (!r) return;
      const line = window.innerHeight * 0.6;
      const active = r.querySelector(".rs.active");
      if (active) {
        const own = [...active.querySelectorAll("[data-target]")].some((btn) => {
          const el = document.getElementById(btn.dataset.target);
          const top = el && el.offsetParent ? el.getBoundingClientRect().top : -1;
          return top >= 0 && top <= line;
        });
        if (own) return;
      }
      let best = null;
      let bestTop = -Infinity;
      r.querySelectorAll("[data-target]").forEach((btn) => {
        const el = document.getElementById(btn.dataset.target);
        if (!el || !el.offsetParent) return;
        const top = el.getBoundingClientRect().top;
        if (top <= line && top > bestTop) {
          bestTop = top;
          best = btn.closest(".rs");
        }
      });
      if (best && !best.classList.contains("active")) setActive(best);
    });
  }, { passive: true });

  const tabs = [...document.querySelectorAll(".tab")];
  function show(id, push) {
    tabs.forEach((t) => t.setAttribute("aria-selected", String(t.dataset.flow === id)));
    document.querySelectorAll(".flow").forEach((f) => (f.hidden = f.id !== "flow-" + id));
    try { localStorage.setItem("walkthrough-tab:" + document.title, id); } catch (e) {}
    if (push) history.replaceState(null, "", "#" + id);
    requestAnimationFrame(layoutVisible);
  }
  tabs.forEach((t) => t.addEventListener("click", () => show(t.dataset.flow, true)));

  let start = location.hash.slice(1);
  if (!tabs.some((t) => t.dataset.flow === start)) {
    try { start = localStorage.getItem("walkthrough-tab:" + document.title) || ""; } catch (e) { start = ""; }
  }
  if (tabs.some((t) => t.dataset.flow === start)) show(start, false);

  let raf = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(layoutVisible);
  });
  if (window.ResizeObserver) {
    let ro = 0;
    new ResizeObserver(() => {
      cancelAnimationFrame(ro);
      ro = requestAnimationFrame(layoutVisible);
    }).observe(document.body);
  }
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(layoutVisible);
  window.addEventListener("load", layoutVisible);
  layoutVisible();
})();
