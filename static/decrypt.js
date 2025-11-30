(() => {
  const btn = document.getElementById('decryptBtn');
  const pwdInput = document.getElementById('decryptPassword');
  const statusEl = document.getElementById('decryptStatus');
  const previewEl = document.getElementById('decryptPreview');
  if (!btn || !pwdInput) return;
  
    // Pre-fill password from URL query (?pwd=...)
    try {
      const params = new URLSearchParams(window.location.search);
      const qp = params.get('pwd');
      if (qp) {
        pwdInput.value = qp;
      }
    } catch (e) {
      // ignore
    }

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg || '';
  }

  async function deriveKey(password, salt, kdf, iterations) {
    const enc = new TextEncoder();
    if (kdf === 'SHA256') {
      const data = new Uint8Array([...salt, ...enc.encode(password)]);
      const digest = await crypto.subtle.digest('SHA-256', data);
      return crypto.subtle.importKey('raw', digest, { name: 'AES-GCM' }, false, ['decrypt']);
    }
    const passKey = await crypto.subtle.importKey('raw', enc.encode(password), { name: 'PBKDF2' }, false, ['deriveKey']);
    return crypto.subtle.deriveKey({ name: 'PBKDF2', salt, iterations, hash: 'SHA-256' }, passKey, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
  }

  function splitEnvelope(buf) {
    // Our format: JSON header + "\n\n--GV--\n\n" + ciphertext
    const delim = new TextEncoder().encode('\n\n--GV--\n\n');
    const bytes = new Uint8Array(buf);
    // Find delimiter
    for (let i = 0; i <= bytes.length - delim.length; i++) {
      let match = true;
      for (let j = 0; j < delim.length; j++) {
        if (bytes[i + j] !== delim[j]) { match = false; break; }
      }
      if (match) {
        const headerBytes = bytes.slice(0, i);
        const cipherBytes = bytes.slice(i + delim.length);
        return { headerBytes, cipherBytes };
      }
    }
    throw new Error('Invalid encrypted format');
  }

  function parseHeader(headerBytes) {
    const txt = new TextDecoder().decode(headerBytes);
    try {
      return JSON.parse(txt);
    } catch (e) {
      throw new Error('Invalid header JSON');
    }
  }

  async function handleDecrypt() {
    previewEl.innerHTML = '';
    const password = pwdInput.value || '';
    if (!password) { setStatus('Please enter a password.'); return; }
    setStatus('Downloading…');
    const rawUrl = btn.getAttribute('data-raw');
    const resp = await fetch(rawUrl, { cache: 'no-store' });
    if (!resp.ok) { setStatus('Fetch failed: ' + resp.status); return; }
    let buf;
    try {
      const contentLength = resp.headers.get('Content-Length');
      if (resp.body && contentLength) {
        const total = parseInt(contentLength, 10) || 0;
        const reader = resp.body.getReader();
        const chunks = [];
        let received = 0;
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(value);
          received += value.length;
          if (total > 0) {
            const pct = ((received / total) * 100).toFixed(1);
            setStatus(`Downloading… ${pct}%`);
          }
        }
        const merged = new Uint8Array(received);
        let offset = 0;
        for (const c of chunks) { merged.set(c, offset); offset += c.length; }
        buf = merged.buffer;
      } else {
        buf = await resp.arrayBuffer();
      }
    } catch (e) {
      setStatus('Download failed: ' + e.message);
      return;
    }

    let headerBytes, cipherBytes, header;
    try {
      ({ headerBytes, cipherBytes } = splitEnvelope(buf));
      header = parseHeader(headerBytes);
    } catch (e) {
      setStatus('Invalid encrypted file: ' + e.message);
      return;
    }

    const salt = new Uint8Array(header.salt);
    const iv = new Uint8Array(header.iv);
    const iterations = header.iterations || 120000;
    const kdf = header.kdf === 'SHA256' ? 'SHA256' : 'PBKDF2';
    let key;
    try {
      key = await deriveKey(password, salt, kdf, iterations);
    } catch (e) {
      setStatus('Key derivation failed');
      return;
    }

    setStatus('Decrypting…');
    let plaintext;
    try {
      plaintext = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, cipherBytes);
    } catch (e) {
      setStatus('Decryption failed. Wrong password?');
      return;
    }

    const type = header.type || 'application/octet-stream';
    const blob = new Blob([new Uint8Array(plaintext)], { type });
    const url = URL.createObjectURL(blob);

    // Render preview based on type
    if (type.startsWith('image/')) {
      const img = document.createElement('img');
      img.className = 'preview';
      img.src = url;
      previewEl.appendChild(img);
    } else if (type.startsWith('text/') || type === 'application/json' || type === 'application/xml') {
      const iframe = document.createElement('iframe');
      iframe.className = 'preview';
      iframe.src = url;
      previewEl.appendChild(iframe);
    } else if (type.startsWith('audio/')) {
      const audio = document.createElement('audio');
      audio.className = 'media';
      audio.controls = true;
      audio.src = url;
      previewEl.appendChild(audio);
    } else if (type.startsWith('video/')) {
      const video = document.createElement('video');
      video.className = 'media';
      video.controls = true;
      video.src = url;
      previewEl.appendChild(video);
    } else {
      const a = document.createElement('a');
      a.href = url;
      a.download = header.filename || 'decrypted';
      a.textContent = 'Download decrypted file';
      previewEl.appendChild(a);
    }

    setStatus('Decrypted. Preview ready.');
  }

  btn.addEventListener('click', (e) => {
    e.preventDefault();
    handleDecrypt().catch(err => setStatus('Error: ' + (err && err.message ? err.message : String(err))));
  });
})();
