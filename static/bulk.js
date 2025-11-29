(() => {
  const form = document.getElementById('bulkDeleteForm');
  if (!form) return;
  const btn = document.getElementById('bulkDeleteBtn');
  const selectAll = document.getElementById('selectAll');
  const boxes = () => Array.from(form.querySelectorAll('.rowChk'));

  function updateState() {
    const any = boxes().some(b => b.checked);
    if (btn) btn.disabled = !any;
  }

  boxes().forEach(b => b.addEventListener('change', updateState));
  if (selectAll) {
    selectAll.addEventListener('change', () => {
      const checked = selectAll.checked;
      boxes().forEach(b => { b.checked = checked; });
      updateState();
    });
  }

  updateState();
})();
