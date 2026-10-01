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
