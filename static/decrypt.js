(() => {
  const btn = document.getElementById('decryptBtn');
  const pwdInput = document.getElementById('decryptPassword');
  const statusEl = document.getElementById('decryptStatus');
  const previewEl = document.getElementById('decryptPreview');
  if (!btn || !pwdInput) return;

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg || '';
  }

  async function deriveKey(password, salt) {
    const enc = new TextEncoder();
    const passKey = await crypto.subtle.importKey('raw', enc.encode(password), { name: 'PBKDF2' }, false, ['deriveKey']);
    return crypto.subtle.deriveKey(
      { name: 'PBKDF2', salt, iterations: 120000, hash: 'SHA-256' },
      passKey,
      { name: 'AES-GCM', length: 256 },
      false,
      ['decrypt']
    );
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
    setStatus('Fetching…');
    const rawUrl = btn.getAttribute('data-raw');
    const resp = await fetch(rawUrl, { cache: 'no-store' });
    if (!resp.ok) { setStatus('Fetch failed: ' + resp.status); return; }
    const buf = await resp.arrayBuffer();

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
    let key;
    try {
      key = await deriveKey(password, salt);
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
