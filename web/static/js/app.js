/**
 * ============================================================
 * Sin'X Manual Poster — Modern Single Page Application (SPA)
 * ============================================================
 */

let authToken = localStorage.getItem('sinx_poster_token') || '';
let currentUser = null;
let currentTab = 'create';
let currentPage = 1;
let sseSource = null;
let isLogAutoScroll = true;
let uploadedVideoData = null; // { video_path, video_filename, video_url, size }

// ---------------------------------------------------------------------------
// Helpers & API Fetch
// ---------------------------------------------------------------------------

function getToken() {
    return authToken || localStorage.getItem('sinx_poster_token') || '';
}

function setAuth(token, user) {
    authToken = token;
    currentUser = user;
    localStorage.setItem('sinx_poster_token', token);
    localStorage.setItem('sinx_poster_user', JSON.stringify(user));
}

function clearAuth() {
    authToken = '';
    currentUser = null;
    localStorage.removeItem('sinx_poster_token');
    localStorage.removeItem('sinx_poster_user');
}

async function apiFetch(url, options = {}) {
    const token = getToken();
    const headers = { ...(options.headers || {}) };
    if (token) headers['X-Auth-Token'] = token;
    if (!(options.body instanceof FormData) && !headers['Content-Type'] && options.body) {
        headers['Content-Type'] = 'application/json';
    }

    const resp = await fetch(url, { ...options, headers });
    if (resp.status === 401) {
        clearAuth();
        showLoginOverlay();
        throw new Error('Sesi telah kedaluwarsa. Silakan login kembali.');
    }
    return resp;
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function formatBytes(bytes, decimals = 2) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

// ---------------------------------------------------------------------------
// Auth UI & Lifecycle
// ---------------------------------------------------------------------------

function showLoginOverlay() {
    const overlay = document.getElementById('login-overlay');
    if (overlay) overlay.style.display = 'flex';
}

function hideLoginOverlay() {
    const overlay = document.getElementById('login-overlay');
    if (overlay) overlay.style.display = 'none';
}

async function handleLogin(e) {
    if (e) e.preventDefault();
    const uInput = document.getElementById('login-username');
    const pInput = document.getElementById('login-password');
    const username = uInput.value.trim();
    const password = pInput.value.trim();

    if (!username || !password) {
        showToast('Username dan password wajib diisi!', 'warning');
        return;
    }

    try {
        const res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            setAuth(data.token, {
                username: data.username,
                account_id: data.account_id,
                is_admin: data.is_admin
            });
            hideLoginOverlay();
            updateUserBadge();
            initDashboard();
            showToast(data.message || 'Login berhasil!', 'success');
        } else {
            showToast(data.detail || 'Login gagal.', 'error');
        }
    } catch (err) {
        showToast('Network error during login: ' + err.message, 'error');
    }
}

async function handleLogout() {
    try {
        await apiFetch('/api/auth/logout', { method: 'POST' });
    } catch (_) {}
    clearAuth();
    showLoginOverlay();
    showToast('Berhasil logout.', 'info');
}

function updateUserBadge() {
    const badgeName = document.getElementById('user-badge-name');
    const badgeRole = document.getElementById('user-badge-role');
    const adminTabs = document.querySelectorAll('.admin-only');

    if (currentUser) {
        if (badgeName) badgeName.innerText = currentUser.username;
        if (badgeRole) badgeRole.innerText = currentUser.is_admin ? 'Admin' : 'Karyawan';
        adminTabs.forEach(el => {
            el.style.display = currentUser.is_admin ? 'inline-flex' : 'none';
        });
    }
}

// ---------------------------------------------------------------------------
// Tabs Switching
// ---------------------------------------------------------------------------

function switchTab(tabName, el) {
    currentTab = tabName;
    document.querySelectorAll('.clay-tab-btn').forEach(btn => btn.classList.remove('active'));
    if (el) el.classList.add('active');

    document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
    const targetContent = document.getElementById(`tab-${tabName}`);
    if (targetContent) targetContent.classList.add('active');

    if (tabName === 'posts') {
        loadPosts(1);
    } else if (tabName === 'platforms') {
        loadPlatformCards();
    } else if (tabName === 'config') {
        loadSettings();
    } else if (tabName === 'logs') {
        initSSELogs();
    } else if (tabName === 'users') {
        loadUsersTable();
    }
}

// ---------------------------------------------------------------------------
// Video Dropzone & Upload
// ---------------------------------------------------------------------------

function initDropzone() {
    const dropzone = document.getElementById('video-dropzone');
    const fileInput = document.getElementById('video-file-input');
    if (!dropzone || !fileInput) return;

    ['dragenter', 'dragover'].forEach(name => {
        dropzone.addEventListener(name, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add('dragover');
        });
    });

    ['dragleave', 'drop'].forEach(name => {
        dropzone.addEventListener(name, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('dragover');
        });
    });

    dropzone.addEventListener('drop', (e) => {
        const files = e.dataTransfer.files;
        if (files && files.length > 0) {
            handleVideoFileSelected(files[0]);
        }
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files && fileInput.files.length > 0) {
            handleVideoFileSelected(fileInput.files[0]);
        }
    });
}

async function handleVideoFileSelected(file) {
    if (!file) return;

    const previewContainer = document.getElementById('video-preview-wrap');
    const videoPlayer = document.getElementById('video-preview-player');
    const videoInfoText = document.getElementById('video-file-info');
    const uploadProgress = document.getElementById('upload-progress-wrap');
    const progressBar = document.getElementById('upload-progress-bar');

    // Auto-fill title if title input is empty
    const titleInput = document.getElementById('post-title');
    if (titleInput && !titleInput.value.trim()) {
        const cleanName = file.name.replace(/\.[^/.]+$/, '').replace(/[-_]/g, ' ');
        titleInput.value = cleanName.charAt(0).toUpperCase() + cleanName.slice(1);
    }

    if (uploadProgress) uploadProgress.style.display = 'block';
    if (progressBar) progressBar.style.width = '30%';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await apiFetch('/api/posts/upload-video', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();

        if (progressBar) progressBar.style.width = '100%';

        if (res.ok && data.success) {
            uploadedVideoData = data;
            if (videoPlayer) videoPlayer.src = data.video_url;
            if (previewContainer) previewContainer.style.display = 'block';
            if (videoInfoText) {
                videoInfoText.innerHTML = `<b>${escapeHtml(data.original_filename)}</b> (${formatBytes(data.video_size_bytes)}) — <span style="color:#10b981;">Siap Diposting</span>`;
            }
            showToast('Video berhasil diupload ke server!', 'success');
        } else {
            showToast(data.detail || 'Gagal mengupload video', 'error');
        }
    } catch (err) {
        showToast('Error uploading video: ' + err.message, 'error');
    } finally {
        setTimeout(() => {
            if (uploadProgress) uploadProgress.style.display = 'none';
        }, 800);
    }
}

function toggleScheduleOptions(isScheduled) {
    const wrap = document.getElementById('schedule-datetime-wrap');
    if (wrap) {
        wrap.style.display = isScheduled ? 'block' : 'none';
    }
}

// ---------------------------------------------------------------------------
// Load Platform Checkboxes
// ---------------------------------------------------------------------------

let cachedPlatforms = [];

async function loadPlatformCheckboxes() {
    const container = document.getElementById('platform-checkboxes-container');
    if (!container) return;

    try {
        const res = await apiFetch('/api/platforms');
        const data = await res.json();
        cachedPlatforms = data.targets || [];

        container.innerHTML = cachedPlatforms.map(p => {
            const isChecked = p.enabled ? 'checked' : '';
            const authPill = p.auth_configured
                ? `<span style="font-size: 10px; background: rgba(16,185,129,0.15); color: #34d399; padding: 1px 6px; border-radius: 4px;">Ready</span>`
                : `<span style="font-size: 10px; background: rgba(239,68,68,0.15); color: #f87171; padding: 1px 6px; border-radius: 4px;">No Cookie</span>`;

            return `
                <label class="platform-checkbox-label ${isChecked ? 'checked' : ''}" id="label-plat-${p.target_key}">
                    <input type="checkbox" name="target_platform" value="${p.target_key}" ${isChecked} onchange="togglePlatformCardStyle('${p.target_key}', this.checked)">
                    <div style="flex: 1;">
                        <div style="font-weight: 600; font-size: 0.9rem; color: var(--text-primary); display: flex; align-items: center; justify-content: space-between;">
                            ${escapeHtml(p.name)}
                            ${authPill}
                        </div>
                        <div style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase;">${escapeHtml(p.platform)}</div>
                    </div>
                </label>
            `;
        }).join('');

    } catch (err) {
        console.error('Error loading platform checkboxes:', err);
    }
}

function togglePlatformCardStyle(targetKey, checked) {
    const label = document.getElementById(`label-plat-${targetKey}`);
    if (label) {
        if (checked) label.classList.add('checked');
        else label.classList.remove('checked');
    }
}

function selectAllPlatforms(select) {
    const checkboxes = document.querySelectorAll('input[name="target_platform"]');
    checkboxes.forEach(cb => {
        cb.checked = select;
        togglePlatformCardStyle(cb.value, select);
    });
}

// ---------------------------------------------------------------------------
// Submit Post
// ---------------------------------------------------------------------------

async function submitManualPost() {
    if (!uploadedVideoData) {
        showToast('Silakan pilih dan upload file video terlebih dahulu!', 'warning');
        return;
    }

    const titleInput = document.getElementById('post-title');
    const descInput = document.getElementById('post-description');
    const tagsInput = document.getElementById('post-tags');
    const timingNow = document.getElementById('timing-now');
    const scheduleInput = document.getElementById('post-scheduled-time');

    const title = titleInput.value.trim();
    if (!title) {
        showToast('Judul video wajib diisi!', 'warning');
        titleInput.focus();
        return;
    }

    // Selected platforms
    const selectedPlatforms = Array.from(document.querySelectorAll('input[name="target_platform"]:checked'))
        .map(cb => cb.value);

    if (selectedPlatforms.length === 0) {
        showToast('Pilih minimal 1 platform tujuan posting!', 'warning');
        return;
    }

    const isPostNow = timingNow.checked;
    let scheduledAt = null;

    if (!isPostNow) {
        const val = scheduleInput.value;
        if (!val) {
            showToast('Silakan tentukan tanggal dan jam jadwal tayang!', 'warning');
            scheduleInput.focus();
            return;
        }
        scheduledAt = val.replace('T', ' ') + ':00';
    }

    // Tags parsing
    const rawTags = tagsInput ? tagsInput.value.trim() : '';
    const tags = rawTags ? rawTags.split(/[\s,]+/).map(t => t.startsWith('#') ? t : `#${t}`).filter(Boolean) : [];

    const payload = {
        title: title,
        description: descInput ? descInput.value.trim() : '',
        tags: tags,
        video_path: uploadedVideoData.video_path,
        video_filename: uploadedVideoData.video_filename,
        video_size_bytes: uploadedVideoData.video_size_bytes || 0,
        target_platforms: selectedPlatforms,
        scheduled_at: scheduledAt,
        post_now: isPostNow
    };

    const submitBtn = document.getElementById('btn-submit-post');
    const origHtml = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i data-lucide="loader-2" class="spin"></i> Memproses...';
    lucide.createIcons();

    try {
        const res = await apiFetch('/api/posts', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
        const data = await res.json();

        if (res.ok && data.success) {
            showToast(data.message || 'Postingan berhasil dibuat!', 'success');
            // Reset Form
            titleInput.value = '';
            if (descInput) descInput.value = '';
            if (tagsInput) tagsInput.value = '';
            uploadedVideoData = null;
            document.getElementById('video-preview-wrap').style.display = 'none';
            document.getElementById('video-preview-player').src = '';
            document.getElementById('video-file-info').innerHTML = '';

            // Redirect to Posts list tab
            const tabBtn = document.querySelector('[data-tab="posts"]');
            switchTab('posts', tabBtn);
        } else {
            showToast(data.detail || 'Gagal menyimpan postingan', 'error');
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = origHtml;
        lucide.createIcons();
    }
}

// ---------------------------------------------------------------------------
// Posts Table & Actions
// ---------------------------------------------------------------------------

async function loadPosts(page = 1) {
    currentPage = page;
    const tbody = document.getElementById('posts-table-body');
    if (!tbody) return;

    const filterStatus = document.getElementById('filter-post-status')?.value || '';

    try {
        const res = await apiFetch(`/api/posts?page=${page}&limit=15&status=${filterStatus}`);
        const data = await res.json();

        tbody.innerHTML = '';
        if (!data.posts || data.posts.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" style="text-align: center; color: var(--text-muted); padding: 3rem 1rem;">
                        <i data-lucide="inbox" style="width: 40px; height: 40px; opacity: 0.3; margin-bottom: 8px; display: block; margin: 0 auto 8px auto;"></i>
                        Belum ada postingan manual. Buat postingan baru di tab 'Upload & Post'!
                    </td>
                </tr>
            `;
            lucide.createIcons();
            return;
        }

        data.posts.forEach(p => {
            let pills = '';
            if (p.platforms && Object.keys(p.platforms).length > 0) {
                for (const [targetKey, pData] of Object.entries(p.platforms)) {
                    const st = pData.status || 'pending';
                    const hasLink = pData.upload_url && pData.upload_url.startsWith('http');
                    if (hasLink) {
                        pills += `<a href="${pData.upload_url}" target="_blank" class="platform-pill ${st}" title="Buka postingan di ${targetKey}" style="text-decoration:none;">${targetKey} ↗</a> `;
                    } else {
                        pills += `<span class="platform-pill ${st}" title="${escapeHtml(pData.error_msg || '')}">${targetKey}: ${st}</span> `;
                    }
                }
            } else {
                pills = '<span style="color: var(--text-muted); font-size: 0.8rem;">-</span>';
            }

            const statusBadgeMap = {
                'draft': 'badge-pending',
                'scheduled': 'badge-pending',
                'uploading': 'badge-uploading',
                'done': 'badge-done',
                'partial': 'badge-done',
                'failed': 'badge-failed'
            };
            const badgeClass = statusBadgeMap[p.status] || 'badge-pending';

            const timingDisplay = p.scheduled_at
                ? `<span title="Dijadwalkan" style="color:#fbbf24;"><i data-lucide="clock" style="width:12px; height:12px; display:inline;"></i> ${escapeHtml(p.scheduled_at)}</span>`
                : `<span title="Dibuat" style="color:var(--text-muted);">${escapeHtml(p.created_at ? p.created_at.substring(0, 16).replace('T', ' ') : '-')}</span>`;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-weight: 700; color: var(--text-muted); font-family: var(--font-mono);">#${p.id}</td>
                <td>
                    <div style="font-weight: 600; color: var(--text-primary); max-width: 240px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${escapeHtml(p.title)}">
                        ${escapeHtml(p.title)}
                    </div>
                    <div style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(p.video_filename || '')}</div>
                </td>
                <td><span class="badge-clay ${badgeClass}">${p.status.toUpperCase()}</span></td>
                <td><div style="display: flex; flex-wrap: wrap; gap: 4px;">${pills}</div></td>
                <td style="font-size: 0.78rem; font-family: var(--font-mono); white-space: nowrap;">${timingDisplay}</td>
                <td style="text-align: center; white-space: nowrap;">
                    ${p.status !== 'done' ? `
                        <button class="btn-clay btn-clay-primary btn-clay-sm" onclick="triggerPostNow(${p.id})" title="Upload / Coba lagi sekarang" style="padding: 4px 8px; margin-right: 4px;">
                            <i data-lucide="send" style="width: 13px; height: 13px;"></i>
                        </button>
                    ` : ''}
                    <button class="btn-clay btn-clay-secondary btn-clay-sm" onclick="deletePostItem(${p.id})" title="Hapus post #${p.id}" style="padding: 4px 8px; color: #ef4444;">
                        <i data-lucide="trash-2" style="width: 13px; height: 13px;"></i>
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });

        const pageInfo = document.getElementById('posts-page-info');
        if (pageInfo) pageInfo.innerText = `Halaman ${data.page} dari ${data.pages || 1} (${data.total} Postingan)`;

        const prevBtn = document.getElementById('btn-posts-prev');
        const nextBtn = document.getElementById('btn-posts-next');
        if (prevBtn) prevBtn.disabled = data.page <= 1;
        if (nextBtn) nextBtn.disabled = data.page >= data.pages;

        lucide.createIcons();
    } catch (err) {
        console.error('Error loading posts:', err);
    }
}

async function triggerPostNow(postId) {
    if (!confirm(`Mulai proses upload sekarang untuk Post #${postId}?`)) return;

    try {
        const res = await apiFetch(`/api/posts/${postId}/publish`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Proses upload dimulai!', 'success');
            loadPosts(currentPage);
        } else {
            showToast(data.detail || 'Gagal memulai upload', 'error');
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
}

async function deletePostItem(postId) {
    if (!confirm(`Hapus Post #${postId} beserta file videonya? Tindakan ini tidak dapat dibatalkan.`)) return;

    try {
        const res = await apiFetch(`/api/posts/${postId}`, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Post berhasil dihapus', 'success');
            loadPosts(currentPage);
        } else {
            showToast(data.detail || 'Gagal menghapus post', 'error');
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
}

// ---------------------------------------------------------------------------
// Platform Targets & Cookies Cards
// ---------------------------------------------------------------------------

async function loadPlatformCards() {
    const container = document.getElementById('platforms-cards-grid');
    if (!container) return;

    try {
        const res = await apiFetch('/api/platforms');
        const data = await res.json();
        const targets = data.targets || [];

        container.innerHTML = targets.map(t => {
            const isConnected = t.auth_configured;
            return `
                <div class="clay-card platform-card" style="display: flex; flex-direction: column; justify-content: space-between; border-radius: 16px;">
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                            <div style="display: flex; align-items: center; gap: 10px;">
                                <div class="platform-clay-badge badge-${t.platform}">
                                    <i data-lucide="share-2" style="width: 18px; height: 18px;"></i>
                                </div>
                                <div>
                                    <h4 style="margin: 0; font-size: 1.05rem; color: var(--text-primary); font-weight: 700;">${escapeHtml(t.name)}</h4>
                                    <span style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase;">${escapeHtml(t.platform)}</span>
                                </div>
                            </div>
                            <label class="clay-switch">
                                <input type="checkbox" ${t.enabled ? 'checked' : ''} onchange="togglePlatformTarget('${t.target_key}', this.checked)">
                                <span class="clay-switch-slider"></span>
                            </label>
                        </div>

                        <div style="display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: rgba(0,0,0,0.25); border-radius: 10px; margin-bottom: 14px;">
                            <span style="font-size: 0.82rem; color: var(--text-muted);">Status Sesi:</span>
                            <span class="badge-clay ${isConnected ? 'badge-done' : 'badge-failed'}" style="font-size: 0.75rem; padding: 2px 8px;">
                                <i data-lucide="${isConnected ? 'check-circle' : 'alert-circle'}" style="width: 12px; height: 12px; display: inline;"></i>
                                ${isConnected ? 'Sesi Aktif' : 'Belum Ada Cookies'}
                            </span>
                        </div>
                    </div>

                    <div style="display: flex; flex-direction: column; gap: 8px;">
                        <input type="file" id="file-cookie-${t.target_key}" style="display: none;" onchange="uploadCookieFile('${t.target_key}', this)">
                        <button class="btn-clay btn-clay-secondary btn-clay-sm" style="width: 100%; justify-content: center;" onclick="document.getElementById('file-cookie-${t.target_key}').click()">
                            <i data-lucide="key" style="width: 14px; height: 14px;"></i> Upload Cookies (.json / .txt)
                        </button>

                        <input type="file" id="file-zip-${t.target_key}" accept=".zip" style="display: none;" onchange="uploadProfileZip('${t.target_key}', this)">
                        <button class="btn-clay btn-clay-secondary btn-clay-sm" style="width: 100%; justify-content: center;" onclick="document.getElementById('file-zip-${t.target_key}').click()">
                            <i data-lucide="archive" style="width: 14px; height: 14px;"></i> Upload Profil (.zip)
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        lucide.createIcons();
    } catch (err) {
        console.error('Error loading platform cards:', err);
    }
}

async function togglePlatformTarget(targetKey, enabled) {
    try {
        const res = await apiFetch(`/api/platforms/${targetKey}`, {
            method: 'PATCH',
            body: JSON.stringify({ enabled })
        });
        if (res.ok) {
            showToast(`Target ${targetKey} ${enabled ? 'diaktifkan' : 'dinonaktifkan'}`, 'info', 2000);
            loadPlatformCheckboxes();
        }
    } catch (err) {
        showToast('Error updating platform: ' + err.message, 'error');
    }
}

async function uploadCookieFile(targetKey, fileInput) {
    if (!fileInput.files || fileInput.files.length === 0) return;
    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append('file', file);
    fileInput.value = '';

    showToast(`Mengunggah cookies untuk ${targetKey}...`, 'info');
    try {
        const res = await apiFetch(`/api/platforms/${targetKey}/upload-cookies`, {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(data.message || 'Cookies berhasil diunggah!', 'success');
            loadPlatformCards();
            loadPlatformCheckboxes();
        } else {
            showToast(data.detail || 'Gagal mengunggah cookies', 'error');
        }
    } catch (err) {
        showToast('Upload error: ' + err.message, 'error');
    }
}

async function uploadProfileZip(targetKey, fileInput) {
    if (!fileInput.files || fileInput.files.length === 0) return;
    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append('file', file);
    fileInput.value = '';

    showToast(`Mengunggah dan mengekstrak profil untuk ${targetKey}...`, 'info');
    try {
        const res = await apiFetch(`/api/platforms/${targetKey}/upload-profile`, {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(data.message || 'Profil .zip berhasil diekstrak!', 'success');
            loadPlatformCards();
            loadPlatformCheckboxes();
        } else {
            showToast(data.detail || 'Gagal mengunggah profil .zip', 'error');
        }
    } catch (err) {
        showToast('Upload error: ' + err.message, 'error');
    }
}

// ---------------------------------------------------------------------------
// Settings & Telegram
// ---------------------------------------------------------------------------

async function loadSettings() {
    try {
        const res = await apiFetch('/api/user/settings');
        const data = await res.json();
        if (res.ok && data.settings) {
            const s = data.settings;
            if (document.getElementById('cfg-timezone')) document.getElementById('cfg-timezone').value = s.timezone || 'Asia/Jakarta';
            if (document.getElementById('cfg-delay')) document.getElementById('cfg-delay').value = s.delay_between_platforms_sec || 25;
            if (document.getElementById('cfg-proxy')) document.getElementById('cfg-proxy').value = s.proxy_url || '';
            if (document.getElementById('cfg-tg-enabled')) document.getElementById('cfg-tg-enabled').checked = Boolean(s.telegram_enabled);
            if (document.getElementById('cfg-tg-token')) document.getElementById('cfg-tg-token').value = s.telegram_bot_token || '';
            if (document.getElementById('cfg-tg-chat-id')) document.getElementById('cfg-tg-chat-id').value = s.telegram_chat_id || '';
        }
    } catch (err) {
        console.error('Error loading settings:', err);
    }
}

async function saveSettings() {
    const payload = {
        timezone: document.getElementById('cfg-timezone')?.value || 'Asia/Jakarta',
        delay_between_platforms_sec: parseInt(document.getElementById('cfg-delay')?.value || 25),
        proxy_url: document.getElementById('cfg-proxy')?.value?.trim() || '',
        telegram_enabled: Boolean(document.getElementById('cfg-tg-enabled')?.checked),
        telegram_bot_token: document.getElementById('cfg-tg-token')?.value?.trim() || '',
        telegram_chat_id: document.getElementById('cfg-tg-chat-id')?.value?.trim() || ''
    };

    try {
        const res = await apiFetch('/api/user/settings', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(data.message || 'Pengaturan berhasil disimpan!', 'success');
        } else {
            showToast(data.detail || 'Gagal menyimpan pengaturan', 'error');
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
}

async function testTelegram() {
    const token = document.getElementById('cfg-tg-token')?.value?.trim();
    const chat_id = document.getElementById('cfg-tg-chat-id')?.value?.trim();

    if (!token || !chat_id) {
        showToast('Bot Token dan Chat ID wajib diisi!', 'warning');
        return;
    }

    showToast('Mengirim pesan tes ke Telegram...', 'info');
    try {
        const res = await apiFetch('/api/user/telegram/test', {
            method: 'POST',
            body: JSON.stringify({ bot_token: token, chat_id: chat_id })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(data.message || 'Pesan tes berhasil dikirim!', 'success');
        } else {
            showToast(data.detail || 'Gagal mengirim pesan tes Telegram', 'error');
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
}

// ---------------------------------------------------------------------------
// Live SSE Logs
// ---------------------------------------------------------------------------

function initSSELogs() {
    const logContainer = document.getElementById('live-logs-terminal');
    if (!logContainer) return;

    if (sseSource) {
        sseSource.close();
    }

    const token = getToken();
    sseSource = new EventSource(`/api/logs/stream?token=${encodeURIComponent(token)}`);

    sseSource.onmessage = (e) => {
        try {
            const entry = JSON.parse(e.data);
            appendLogEntry(entry);
        } catch (_) {}
    };

    sseSource.onerror = () => {
        // Retry silently
    };
}

function appendLogEntry(entry) {
    const logContainer = document.getElementById('live-logs-terminal');
    if (!logContainer) return;

    const row = document.createElement('div');
    row.className = `log-line log-${entry.level.toLowerCase()}`;
    row.innerHTML = `<span class="log-time">[${entry.time}]</span> <span class="log-level">[${entry.level}]</span> <span class="log-msg">${escapeHtml(entry.msg)}</span>`;
    logContainer.appendChild(row);

    if (isLogAutoScroll) {
        logContainer.scrollTop = logContainer.scrollHeight;
    }
}

async function clearTerminalLogs() {
    try {
        await apiFetch('/api/logs/clear', { method: 'POST' });
        const logContainer = document.getElementById('live-logs-terminal');
        if (logContainer) logContainer.innerHTML = '';
        showToast('Log terminal dibersihkan.', 'info');
    } catch (_) {}
}

function toggleLogAutoScroll() {
    isLogAutoScroll = !isLogAutoScroll;
    const btn = document.getElementById('btn-toggle-autoscroll');
    if (btn) {
        btn.innerText = `Auto-Scroll: ${isLogAutoScroll ? 'ON' : 'OFF'}`;
    }
}

// ---------------------------------------------------------------------------
// User Management (Admin Only)
// ---------------------------------------------------------------------------

async function loadUsersTable() {
    const tbody = document.getElementById('users-table-body');
    if (!tbody) return;

    try {
        const res = await apiFetch('/api/admin/users');
        const data = await res.json();
        const users = data.users || [];

        tbody.innerHTML = users.map(u => {
            const roleBadge = u.is_admin
                ? `<span style="background: rgba(168,85,247,0.15); color: #c084fc; padding: 2px 8px; border-radius: 50px; font-size: 11px; font-weight: 700;">Admin</span>`
                : `<span style="background: rgba(16,185,129,0.15); color: #6ee7b7; padding: 2px 8px; border-radius: 50px; font-size: 11px; font-weight: 700;">Karyawan</span>`;

            return `
                <tr>
                    <td style="font-family: var(--font-mono); color: var(--text-muted);">#${u.id}</td>
                    <td style="font-weight: 700; color: var(--text-primary);">${escapeHtml(u.username)}</td>
                    <td>${escapeHtml(u.account_name || '-')}</td>
                    <td>${roleBadge}</td>
                    <td style="font-size: 0.78rem; color: var(--text-muted);">${escapeHtml(u.created_at || '-')}</td>
                    <td style="text-align: center;">
                        ${!u.is_admin ? `
                            <button class="btn-clay btn-clay-secondary btn-clay-sm" onclick="deleteUserItem(${u.id}, '${escapeHtml(u.username)}')" style="color: #ef4444; padding: 4px 8px;">
                                <i data-lucide="trash-2" style="width: 13px; height: 13px;"></i>
                            </button>
                        ` : '<span style="color:var(--text-muted); font-size: 11px;">Primary</span>'}
                    </td>
                </tr>
            `;
        }).join('');

        lucide.createIcons();
    } catch (err) {
        console.error('Error loading users:', err);
    }
}

async function createEmployeeUser() {
    const username = document.getElementById('modal-username')?.value.trim();
    const password = document.getElementById('modal-password')?.value.trim();
    const accountName = document.getElementById('modal-account-name')?.value.trim();
    const isAdmin = Boolean(document.getElementById('modal-is-admin')?.checked);

    if (!username || !password) {
        showToast('Username dan password wajib diisi!', 'warning');
        return;
    }

    try {
        const res = await apiFetch('/api/admin/users', {
            method: 'POST',
            body: JSON.stringify({
                username,
                password,
                account_name: accountName || username,
                is_admin: isAdmin
            })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(data.message || 'User berhasil dibuat!', 'success');
            closeModal('modal-create-user');
            loadUsersTable();
        } else {
            showToast(data.detail || 'Gagal membuat user', 'error');
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
}

async function deleteUserItem(userId, username) {
    if (!confirm(`Hapus akun karyawan '${username}'? Semua antrean post milik user ini akan ikut terhapus.`)) return;

    try {
        const res = await apiFetch(`/api/admin/users/${userId}`, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'User berhasil dihapus', 'success');
            loadUsersTable();
        } else {
            showToast(data.detail || 'Gagal menghapus user', 'error');
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
}

function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'flex';
}

function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
}

// ---------------------------------------------------------------------------
// Dashboard Init
// ---------------------------------------------------------------------------

async function initDashboard() {
    try {
        const res = await apiFetch('/api/status');
        const data = await res.json();
        if (res.ok) {
            currentUser = data.current_user;
            updateUserBadge();

            const st = data.stats || {};
            if (document.getElementById('stat-total-posts')) document.getElementById('stat-total-posts').innerText = st.total_posts || 0;
            if (document.getElementById('stat-scheduled')) document.getElementById('stat-scheduled').innerText = st.scheduled || 0;
            if (document.getElementById('stat-done')) document.getElementById('stat-done').innerText = st.done || 0;
            if (document.getElementById('stat-failed')) document.getElementById('stat-failed').innerText = st.failed || 0;

            const schedBadge = document.getElementById('badge-scheduler-status');
            if (schedBadge) {
                schedBadge.innerText = data.scheduler_running ? 'Scheduler Aktif' : 'Scheduler Berhenti';
                schedBadge.className = `badge-clay ${data.scheduler_running ? 'badge-done' : 'badge-failed'}`;
            }
        }
    } catch (_) {}

    loadPlatformCheckboxes();
    initDropzone();
}

window.addEventListener('DOMContentLoaded', () => {
    lucide.createIcons();

    const storedUser = localStorage.getItem('sinx_poster_user');
    if (storedUser) {
        try { currentUser = JSON.parse(storedUser); } catch (_) {}
    }

    if (getToken()) {
        hideLoginOverlay();
        updateUserBadge();
        initDashboard();
    } else {
        showLoginOverlay();
    }
});
