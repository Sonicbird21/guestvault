(() => {
  // Confirm handler for forms with data-confirm attribute
  document.addEventListener('submit', (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    const msg = form.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) {
      e.preventDefault();
    }
  });

  // Hydrate JSON preview if present
  window.addEventListener('DOMContentLoaded', async () => {
    const pre = document.getElementById('jsonPreview');
    if (!pre) return;
    const rawUrl = pre.getAttribute('data-raw');
    if (!rawUrl) return;
    try {
      const res = await fetch(rawUrl, { credentials: 'same-origin' });
      const text = await res.text();
      try {
        const obj = JSON.parse(text);
        pre.textContent = JSON.stringify(obj, null, 2);
      } catch {
        // Fallback to raw text if not valid JSON
        pre.textContent = text;
      }
    } catch (err) {
      pre.textContent = 'Failed to load preview.';
    }
  });
})();
