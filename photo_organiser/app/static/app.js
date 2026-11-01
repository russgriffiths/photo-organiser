// Settings: move date sources up and down. The form submits ticked sources in list order.
(function () {
  const list = document.getElementById("date-sources");
  if (!list) return;
  list.addEventListener("click", (e) => {
    const button = e.target.closest("button[data-move]");
    if (!button) return;
    const item = button.closest("li");
    if (button.dataset.move === "up" && item.previousElementSibling) {
      list.insertBefore(item, item.previousElementSibling);
    } else if (button.dataset.move === "down" && item.nextElementSibling) {
      list.insertBefore(item.nextElementSibling, item);
    }
    button.focus();
  });
})();

// Polls run progress on the dashboard every 2 seconds; reloads once the run finishes.
(function () {
  const box = document.getElementById("progress");
  if (!box) return;
  const text = document.getElementById("progress-text");
  const bar = document.getElementById("progress-bar");
  let wasBusy = false;

  async function poll() {
    try {
      const res = await fetch(box.dataset.statusUrl, { credentials: "same-origin" });
      const data = await res.json();
      if (data.busy) {
        wasBusy = true;
        box.hidden = false;
        const p = data.progress || {};
        const label = (p.kind || "run") + (p.dry_run ? " (dry run)" : "");
        const n = (x) => Number(x).toLocaleString();
        const count = p.total ? ` ${n(p.done)} of ${n(p.total)}` : p.done ? ` ${n(p.done)}` : "";
        text.textContent = `${label}: ${p.stage || "working"}${count}`;
        bar.max = p.total || 1;
        bar.value = p.total ? p.done : 0;
      } else if (wasBusy) {
        window.location.reload();
        return;
      } else {
        box.hidden = true;
      }
    } catch (e) {
      text.textContent = "Lost contact with the server; retrying…";
    }
    setTimeout(poll, 2000);
  }
  poll();
})();
