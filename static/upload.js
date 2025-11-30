(() => {
  const form = document.getElementById('uploadForm');
  if (!form) return;
  const fileInput = document.getElementById('fileInput');
  const passwordInput = document.getElementById('passwordInput');
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

  // No show/hide button per design

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

  const DEFAULT_ITERATIONS = 120000; // strong by default

  async function deriveKeyFromPassword(password, salt, iterations) {
    const enc = new TextEncoder();
    const passKey = await crypto.subtle.importKey('raw', enc.encode(password), { name: 'PBKDF2' }, false, ['deriveKey']);
    return crypto.subtle.deriveKey({ name: 'PBKDF2', salt, iterations, hash: 'SHA-256' }, passKey, { name: 'AES-GCM', length: 256 }, false, ['encrypt']);
  }

  async function encryptFileBlob(file) {
    const password = (passwordInput && passwordInput.value) || '';
    if (!password) return null; // No encryption requested
    const arrayBuf = await file.arrayBuffer();
    const salt = crypto.getRandomValues(new Uint8Array(16));
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const key = await deriveKeyFromPassword(password, salt, DEFAULT_ITERATIONS);
    const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, arrayBuf);
    const meta = {
      v: 1,
      alg: 'AES-GCM',
      kdf: 'PBKDF2-SHA256',
      iterations: DEFAULT_ITERATIONS,
      salt: Array.from(salt),
      iv: Array.from(iv),
      filename: file.name,
      type: file.type || 'application/octet-stream',
      size: file.size
    };
    const header = new TextEncoder().encode(JSON.stringify(meta));
    const delim = new TextEncoder().encode('\n\n--GV--\n\n');
    const combined = new Blob([header, delim, new Uint8Array(ciphertext)], { type: 'application/octet-stream' });
    return { blob: combined, encrypted: true };
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!fileInput.files.length) return;
    const file = fileInput.files[0];
    xhr = new XMLHttpRequest();
    const data = new FormData();
    let encryptedPayload = null;
    try {
      encryptedPayload = await encryptFileBlob(file);
    } catch (err) {
      progressStats.textContent = 'Encryption failed: ' + (err && err.message ? err.message : String(err));
      return;
    }
    if (encryptedPayload && encryptedPayload.encrypted) {
      data.append('file', encryptedPayload.blob, file.name + '.enc');
      data.append('encrypted', '1');
    } else {
      data.append('file', file);
      data.append('encrypted', '0');
    }
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
