(() => {
  const form = document.getElementById('uploadForm');
  if (!form) return;
  const fileInput = document.getElementById('fileInput');
  const uploadBtn = document.getElementById('uploadBtn');
  const cancelBtn = document.getElementById('cancelBtn');
  const progressContainer = document.getElementById('progressContainer');
  const progressFill = document.getElementById('progressFill');
  const progressStats = document.getElementById('progressStats');
  let xhr = null;
  let startTime = 0;

  function resetUI() {
    try {
      form.classList.remove('uploading');
      cancelBtn.style.display = 'none';
      progressContainer.style.display = 'none';
      progressFill.style.width = '0%';
      progressStats.textContent = '';
      uploadBtn.disabled = false;
      fileInput.disabled = false;
    } catch (e) { /* noop */ }
  }

  // Ensure a clean initial state even after bfcache/back navigation
  resetUI();
  window.addEventListener('pageshow', (e) => {
    if (e.persisted) resetUI();
  });
  fileInput.addEventListener('change', () => {
    if (!fileInput.files || fileInput.files.length === 0) resetUI();
  });

  function fmtBytes(bytes) {
    const units = ['B','KB','MB','GB','TB'];
    let size = bytes;
    let i = 0;
    while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
    return `${size.toFixed(2)} ${units[i]}`;
  }

  function fmtTime(seconds) {
    if (!isFinite(seconds)) return '∞';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const m = Math.floor(seconds/60);
    const s = Math.round(seconds%60);
    return `${m}m ${s}s`;
  }

  cancelBtn.addEventListener('click', () => {
    if (xhr) {
      xhr.abort();
      progressStats.textContent = 'Upload canceled';
      resetUI();
    }
  });

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!fileInput.files.length) return;
    const file = fileInput.files[0];
    xhr = new XMLHttpRequest();
    const data = new FormData();
    data.append('file', file);
    startTime = performance.now();
    progressContainer.style.display = 'block';
    cancelBtn.style.display = 'inline-block';
    form.classList.add('uploading');
    progressStats.textContent = 'Starting…';

    xhr.upload.onprogress = (ev) => {
      if (!ev.lengthComputable) return;
      const elapsed = (performance.now() - startTime) / 1000;
      const loaded = ev.loaded;
      const total = ev.total;
      const pct = (loaded / total) * 100;
      progressFill.style.width = pct.toFixed(2) + '%';
      const speed = loaded / elapsed; // bytes/sec
      const remaining = total - loaded;
      const eta = remaining / (speed || 1);
      progressStats.innerHTML = `<span>${pct.toFixed(1)}%</span><span>${fmtBytes(loaded)} / ${fmtBytes(total)}</span><span>${fmtBytes(speed)}/s</span><span>ETA ${fmtTime(eta)}</span>`;
    };

    xhr.onreadystatechange = () => {
      if (xhr.readyState === 4) {
        cancelBtn.style.display = 'none';
        form.classList.remove('uploading');
        if (xhr.status >= 200 && xhr.status < 300) {
          // If server redirected, responseURL should be detail page
          const target = xhr.responseURL || window.location.href;
          progressFill.style.width = '100%';
          progressStats.innerHTML += ' <span>Done</span>';
          window.location.href = target;
        } else if (xhr.status === 0) {
          // Aborted
        } else {
          progressStats.textContent = 'Error: ' + xhr.status + ' ' + xhr.statusText;
          uploadBtn.disabled = false;
          fileInput.disabled = false;
          // Auto-hide the progress UI after a short delay
          setTimeout(resetUI, 4000);
        }
      }
    };

    xhr.open('POST', form.action, true);
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) {
      xhr.setRequestHeader('X-CSRF-Token', meta.getAttribute('content') || '');
    }
    xhr.send(data);
  });
})();
