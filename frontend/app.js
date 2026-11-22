(() => {
  "use strict";

  const STORAGE_KEYS = {
    apiUrl: "vd_api_url",
    apiKey: "vd_api_key",
    history: "vd_history",
    colorScheme: "color-scheme",
  };

  const MAX_HISTORY_ITEMS = 20;

  const PLATFORM_RULES = [
    { id: "youtube", hosts: ["youtube.com", "youtu.be", "youtube-nocookie.com"] },
    { id: "twitter", hosts: ["twitter.com", "x.com", "fxtwitter.com", "vxtwitter.com", "fixupx.com"] },
    { id: "instagram", hosts: ["instagram.com", "instagr.am"] },
    { id: "facebook", hosts: ["facebook.com", "fb.watch", "fb.com"] },
  ];

  const PLATFORM_LABELS = {
    youtube: "YouTube",
    twitter: "X (Twitter)",
    instagram: "Instagram",
    facebook: "Facebook",
    other: "Diğer",
  };

  function safeStorageGet(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  function safeStorageSet(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      // Ignore storage quota or restricted-mode errors
    }
  }

  function safeStorageRemove(key) {
    try {
      localStorage.removeItem(key);
    } catch {
      // Ignore storage errors
    }
  }

  function defaultApiUrl() {
    const host = window.location.hostname;
    if (host === "localhost" || host === "127.0.0.1") {
      return "http://localhost:8000";
    }
    return "https://api-indir.mesutpeker.com";
  }

  function normalizeBaseUrl(rawUrl) {
    const cleaned = (rawUrl || "").trim().replace(/\/+$/, "");
    if (!cleaned) return "";
    try {
      const parsed = new URL(cleaned);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        return "";
      }
      return cleaned;
    } catch {
      return "";
    }
  }

  function sanitizeHttpUrl(rawUrl) {
    if (typeof rawUrl !== "string") return null;
    const trimmed = rawUrl.trim();
    if (!trimmed) return null;
    try {
      const parsed = new URL(trimmed);
      if (parsed.protocol === "http:" || parsed.protocol === "https:") {
        return parsed.toString();
      }
    } catch {
      return null;
    }
    return null;
  }

  function detectPlatformFromUrl(rawUrl) {
    const validUrl = sanitizeHttpUrl(rawUrl);
    if (!validUrl) return null;
    try {
      const host = new URL(validUrl).hostname.toLowerCase().replace(/\.$/, "");
      for (const rule of PLATFORM_RULES) {
        if (rule.hosts.some((domain) => host === domain || host.endsWith(`.${domain}`))) {
          return rule.id;
        }
      }
    } catch {
      return null;
    }
    return null;
  }

  function formatDuration(seconds) {
    if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) {
      return "";
    }
    const total = Math.floor(seconds);
    const hrs = Math.floor(total / 3600);
    const mins = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return hrs > 0 ? `${hrs}:${pad(mins)}:${pad(secs)}` : `${mins}:${pad(secs)}`;
  }

  function formatBytes(bytes) {
    if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes <= 0) {
      return "";
    }
    if (bytes >= 1024 * 1024 * 1024) {
      return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
    }
    if (bytes >= 1024 * 1024) {
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }
    if (bytes >= 1024) {
      return `${Math.round(bytes / 1024)} KB`;
    }
    return `${bytes} B`;
  }

  // ---------------------------------------------------------------------------
  // Theme Controller (dark-mode & dark-mode-toggle guidance)
  // ---------------------------------------------------------------------------
  const colorSchemeMeta = document.querySelector('meta[name="color-scheme"]');
  const systemDarkMedia = window.matchMedia("(prefers-color-scheme: dark)");
  const themeSystemLabel = document.getElementById("theme-system-label");
  const themeRadios = document.querySelectorAll('input[name="themeMode"]');

  function updateSystemThemeLabel() {
    if (!themeSystemLabel) return;
    themeSystemLabel.textContent = systemDarkMedia.matches
      ? "Sistem (Şu an koyu)"
      : "Sistem (Şu an açık)";
  }

  function syncThemeUI() {
    const stored = safeStorageGet(STORAGE_KEYS.colorScheme);
    const activeMode = stored === "light" || stored === "dark" ? stored : "system";
    if (colorSchemeMeta) {
      colorSchemeMeta.content = activeMode === "system" ? "light dark" : activeMode;
    }
    themeRadios.forEach((radio) => {
      radio.checked = radio.value === activeMode;
    });
    updateSystemThemeLabel();
  }

  function applyThemeSelection(mode) {
    if (mode === "light" || mode === "dark") {
      safeStorageSet(STORAGE_KEYS.colorScheme, mode);
    } else {
      safeStorageRemove(STORAGE_KEYS.colorScheme);
    }
    syncThemeUI();
  }

  themeRadios.forEach((radio) => {
    radio.addEventListener("change", (event) => {
      if (event.target.checked) {
        applyThemeSelection(event.target.value);
      }
    });
  });

  // Never erase a stored override on system change; only refresh the label text
  if (typeof systemDarkMedia.addEventListener === "function") {
    systemDarkMedia.addEventListener("change", updateSystemThemeLabel);
  }

  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEYS.colorScheme) {
      syncThemeUI();
    }
  });

  // ---------------------------------------------------------------------------
  // Top-Layer Dialog Exit & Light-Dismiss Fallback
  // (animate-to-from-top-layer & light-dismiss-a-dialog)
  // ---------------------------------------------------------------------------
  let supportsDisplayTransition;
  function canTransitionDisplay() {
    if (supportsDisplayTransition !== undefined) return supportsDisplayTransition;
    if (!window.CSS?.supports?.("transition-behavior", "allow-discrete") || !document.body) {
      return false;
    }
    const probe = document.createElement("div");
    probe.style.cssText = "transition: display 1s allow-discrete !important; display: block;";
    document.body.appendChild(probe);
    getComputedStyle(probe).display;
    probe.style.display = "none";
    supportsDisplayTransition = getComputedStyle(probe).display === "block";
    probe.remove();
    return supportsDisplayTransition;
  }

  function supportsTopLayerExit() {
    return Boolean(window.CSS?.supports?.("overlay", "auto") && canTransitionDisplay());
  }

  async function closeTopLayer(dialog) {
    if (!dialog.open) return;
    if (!supportsTopLayerExit()) {
      dialog.setAttribute("data-closing", "");
      const animations = dialog.getAnimations({ subtree: true });
      if (animations.length > 0) {
        await Promise.race([
          Promise.allSettled(animations.map((a) => a.finished)),
          new Promise((resolve) => setTimeout(resolve, 2000)),
        ]);
      }
      if (!dialog.hasAttribute("data-closing")) return;
      dialog.removeAttribute("data-closing");
    }
    dialog.close();
  }

  function wireModalDialog(dialog, closeButton) {
    if (!dialog) return;

    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeTopLayer(dialog);
    });

    if (closeButton) {
      closeButton.addEventListener("click", () => {
        closeTopLayer(dialog);
      });
    }

    if (!("closedBy" in HTMLDialogElement.prototype)) {
      dialog.addEventListener("click", (event) => {
        if (event.target !== dialog) return;
        const rect = dialog.getBoundingClientRect();
        const inside =
          rect.top <= event.clientY &&
          event.clientY <= rect.top + rect.height &&
          rect.left <= event.clientX &&
          event.clientX <= rect.left + rect.width;
        if (inside) return;
        closeTopLayer(dialog);
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Form Validation After Interaction & Consistent ARIA Sync
  // ---------------------------------------------------------------------------
  function initFormValidationA11y() {
    const linkError = (el, shown) => {
      const errorId = el.dataset.error;
      if (!errorId) return;
      const ids = (el.getAttribute("aria-describedby") || "")
        .split(/\s+/)
        .filter((id) => id && id !== errorId);
      if (shown) ids.push(errorId);
      if (ids.length) el.setAttribute("aria-describedby", ids.join(" "));
      else el.removeAttribute("aria-describedby");
    };

    const announcer = document.createElement("div");
    announcer.setAttribute("aria-live", "polite");
    announcer.classList.add("visually-hidden");
    document.body.append(announcer);
    let announceTimer;
    let announcedField;

    const spokenText = (node) => {
      const copy = node.cloneNode(true);
      copy.querySelectorAll('[aria-hidden="true"]').forEach((n) => n.remove());
      copy
        .querySelectorAll('[role="img"][aria-label]')
        .forEach((n) => n.replaceWith(`${n.getAttribute("aria-label")}: `));
      return copy.textContent.replace(/\s+/g, " ").trim();
    };

    const announceError = (el) => {
      const error = document.getElementById(el.dataset.error);
      if (!error) return;
      const label = el.labels?.[0] ? `${spokenText(el.labels[0])}: ` : "";
      clearTimeout(announceTimer);
      announcer.textContent = "";
      announcedField = el;
      announceTimer = setTimeout(() => {
        announcer.textContent = label + spokenText(error);
      }, 500);
    };

    const flagged = new WeakSet();
    const announced = new WeakSet();
    const supportsUserInvalid = CSS.supports("selector(:user-invalid)");
    const fallbackState = new WeakMap();

    const syncAria = (el, announce = false) => {
      if (!el.matches?.("input, select, textarea")) return;
      let invalid = false;
      if (supportsUserInvalid) {
        invalid = el.matches(":user-invalid");
      } else {
        const state = fallbackState.get(el);
        const committed = Boolean(state?.hasBlurred && state?.hasInteracted);
        invalid = committed && !el.validity.valid;
        el.classList.toggle("user-invalid-fallback", committed && !el.validity.valid);
        el.classList.toggle("user-valid-fallback", committed && el.validity.valid);
      }

      if (invalid) {
        if (announce && !announced.has(el)) {
          announceError(el);
          announced.add(el);
        }
        el.setAttribute("aria-invalid", "true");
        linkError(el, true);
        flagged.add(el);
      } else if (flagged.has(el) || el.getAttribute("aria-invalid") !== "true") {
        el.setAttribute("aria-invalid", "false");
        linkError(el, false);
        flagged.delete(el);
        announced.delete(el);
        if (announcedField === el) {
          clearTimeout(announceTimer);
          announcer.textContent = "";
        }
      }
    };

    document.querySelectorAll("input, select, textarea").forEach((el) => {
      syncAria(el);
    });

    document.addEventListener(
      "blur",
      (event) => {
        const el = event.target;
        if (!supportsUserInvalid && el.matches?.("input, select, textarea")) {
          const state = fallbackState.get(el) || { hasInteracted: false, hasBlurred: false };
          state.hasBlurred = true;
          fallbackState.set(el, state);
        }
        syncAria(el, true);
      },
      true
    );

    document.addEventListener("input", (event) => {
      const el = event.target;
      if (!supportsUserInvalid && el.matches?.("input, select, textarea")) {
        const state = fallbackState.get(el) || { hasInteracted: false, hasBlurred: false };
        state.hasInteracted = true;
        fallbackState.set(el, state);
      }
      if (el.hasAttribute?.("aria-invalid")) {
        syncAria(el);
      }
    });

    document.addEventListener(
      "change",
      (event) => {
        syncAria(event.target, true);
      },
      true
    );

    document.addEventListener(
      "invalid",
      (event) => {
        const el = event.target;
        if (!supportsUserInvalid && el.matches?.("input, select, textarea")) {
          fallbackState.set(el, { hasInteracted: true, hasBlurred: true });
        }
        announced.add(el);
        syncAria(el);
      },
      true
    );

    document.addEventListener(
      "reset",
      (event) => {
        setTimeout(() => {
          [...(event.target.elements || [])].forEach((el) => {
            fallbackState.delete(el);
            el.classList?.remove("user-invalid-fallback", "user-valid-fallback");
            syncAria(el);
          });
        });
      },
      true
    );
  }

  // ---------------------------------------------------------------------------
  // Application State & DOM Elements
  // ---------------------------------------------------------------------------
  const state = {
    apiUrl: normalizeBaseUrl(safeStorageGet(STORAGE_KEYS.apiUrl)) || defaultApiUrl(),
    apiKey: (safeStorageGet(STORAGE_KEYS.apiKey) || "").trim(),
    activeJobId: null,
    pollTimerId: null,
    isBusy: false,
    serverInfo: null,
  };

  const els = {
    connectionPill: document.getElementById("connection-pill"),
    connectionPillText: document.getElementById("connection-pill-text"),
    openSettingsBtn: document.getElementById("open-settings-btn"),

    authView: document.getElementById("auth-view"),
    authForm: document.getElementById("auth-form"),
    authApiUrl: document.getElementById("auth-api-url"),
    authApiKey: document.getElementById("auth-api-key"),
    authFeedback: document.getElementById("auth-feedback"),
    authSubmitBtn: document.getElementById("auth-submit-btn"),

    appView: document.getElementById("app-view"),
    downloadForm: document.getElementById("download-form"),
    videoUrl: document.getElementById("video-url"),
    pasteBtn: document.getElementById("paste-btn"),
    clearBtn: document.getElementById("clear-btn"),
    previewBtn: document.getElementById("preview-btn"),
    downloadBtn: document.getElementById("download-btn"),
    actionFeedback: document.getElementById("action-feedback"),
    platformChips: document.querySelectorAll(".platform-chip"),

    previewCard: document.getElementById("preview-card"),
    previewThumb: document.getElementById("preview-thumb"),
    previewThumbFallback: document.getElementById("preview-thumb-fallback"),
    previewDuration: document.getElementById("preview-duration"),
    previewPlatform: document.getElementById("preview-platform"),
    previewUploader: document.getElementById("preview-uploader"),
    previewTitle: document.getElementById("preview-title"),

    jobCard: document.getElementById("job-card"),
    jobPlatformBadge: document.getElementById("job-platform-badge"),
    jobStatusTitle: document.getElementById("job-status-title"),
    jobPercent: document.getElementById("job-percent"),
    jobProgress: document.getElementById("job-progress"),
    jobDetailText: document.getElementById("job-detail-text"),
    cancelJobBtn: document.getElementById("cancel-job-btn"),

    readyBox: document.getElementById("ready-box"),
    readyFilename: document.getElementById("ready-filename"),
    readyFilesize: document.getElementById("ready-filesize"),
    saveFileLink: document.getElementById("save-file-link"),
    dismissReadyBtn: document.getElementById("dismiss-ready-btn"),

    historyEmpty: document.getElementById("history-empty"),
    historyList: document.getElementById("history-list"),
    clearHistoryBtn: document.getElementById("clear-history-btn"),
    footerEngineInfo: document.getElementById("footer-engine-info"),

    settingsDialog: document.getElementById("settings-dialog"),
    closeSettingsBtn: document.getElementById("close-settings-btn"),
    settingsForm: document.getElementById("settings-form"),
    settingsApiUrl: document.getElementById("settings-api-url"),
    settingsApiKey: document.getElementById("settings-api-key"),
    settingsServerMeta: document.getElementById("settings-server-meta"),
    settingsFeedback: document.getElementById("settings-feedback"),
    settingsSaveBtn: document.getElementById("settings-save-btn"),
    disconnectBtn: document.getElementById("disconnect-btn"),
  };

  function setBanner(el, message, tone = "info") {
    if (!el) return;
    if (!message) {
      el.hidden = true;
      el.textContent = "";
      el.removeAttribute("data-tone");
      return;
    }
    el.textContent = message;
    el.dataset.tone = tone;
    el.hidden = false;
  }

  function setConnectionStatus(statusState, text) {
    els.connectionPill.dataset.state = statusState;
    els.connectionPillText.textContent = text;
  }

  function updatePlatformChips(urlValue) {
    const active = detectPlatformFromUrl(urlValue);
    els.platformChips.forEach((chip) => {
      chip.dataset.active = chip.dataset.platform === active ? "true" : "false";
    });
  }

  function showAuthScreen(message = "", tone = "error") {
    els.authView.hidden = false;
    els.appView.hidden = true;
    els.authApiUrl.value = state.apiUrl;
    els.authApiKey.value = state.apiKey;
    setBanner(els.authFeedback, message, tone);
  }

  function showAppScreen() {
    els.authView.hidden = true;
    els.appView.hidden = false;
    setBanner(els.authFeedback, "");
  }

  function setFormBusy(busy) {
    state.isBusy = busy;
    els.previewBtn.disabled = busy;
    els.downloadBtn.disabled = busy;
  }

  // ---------------------------------------------------------------------------
  // API Client
  // ---------------------------------------------------------------------------
  async function apiRequest(path, { method = "GET", body = null, apiUrl = state.apiUrl, apiKey = state.apiKey } = {}) {
    const base = normalizeBaseUrl(apiUrl);
    if (!base) {
      throw new Error("Geçerli bir API sunucu adresi girin.");
    }

    const headers = {};
    if (apiKey) {
      headers["X-API-Key"] = apiKey;
    }
    if (body !== null) {
      headers["Content-Type"] = "application/json";
    }

    let response;
    try {
      response = await fetch(`${base}${path}`, {
        method,
        headers,
        body: body !== null ? JSON.stringify(body) : undefined,
        mode: "cors",
        credentials: "omit",
      });
    } catch {
      throw new Error(
        `Sunucuya ulaşılamadı (${base}). Backend ve Cloudflare Tunnel'ın çalıştığından emin olun.`
      );
    }

    let payload = null;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      payload = await response.json().catch(() => null);
    }

    if (!response.ok) {
      const detail = payload?.detail || `Sunucu hatası (${response.status})`;
      const err = new Error(detail);
      err.status = response.status;
      throw err;
    }

    return payload;
  }

  function updateServerMetadata(info) {
    state.serverInfo = info;
    if (!info) {
      els.settingsServerMeta.hidden = true;
      els.settingsServerMeta.textContent = "";
      return;
    }

    const parts = [
      `yt-dlp ${info.yt_dlp_version || "?"}`,
      `ffmpeg: ${info.ffmpeg ? "Hazır" : "Eksik"}`,
    ];
    if (Array.isArray(info.js_runtimes) && info.js_runtimes.length > 0) {
      parts.push(`JS: ${info.js_runtimes.join(", ")}`);
    }
    if (typeof info.max_filesize_mb === "number" && info.max_filesize_mb > 0) {
      parts.push(`Limit: ${info.max_filesize_mb} MB`);
    }
    const summary = parts.join(" · ");
    els.footerEngineInfo.textContent = summary;
    els.settingsServerMeta.textContent = `Bağlı sunucu: ${summary}`;
    els.settingsServerMeta.hidden = false;
  }

  async function verifyCredentials(apiUrl, apiKey) {
    const info = await apiRequest("/api/auth/verify", { apiUrl, apiKey });
    state.apiUrl = normalizeBaseUrl(apiUrl);
    state.apiKey = apiKey.trim();
    safeStorageSet(STORAGE_KEYS.apiUrl, state.apiUrl);
    safeStorageSet(STORAGE_KEYS.apiKey, state.apiKey);
    updateServerMetadata(info);
    setConnectionStatus("online", "Bağlı");
    return info;
  }

  // ---------------------------------------------------------------------------
  // Preview & Job Rendering (Strictly XSS-safe DOM updates)
  // ---------------------------------------------------------------------------
  function renderPreview(info) {
    if (!info) {
      els.previewCard.hidden = true;
      return;
    }
    els.previewPlatform.textContent = info.platform_label || PLATFORM_LABELS[info.platform] || "Video";
    els.previewUploader.textContent = info.uploader || "";
    els.previewTitle.textContent = info.title || "Video";

    const durationStr = formatDuration(info.duration);
    if (durationStr) {
      els.previewDuration.textContent = durationStr;
      els.previewDuration.hidden = false;
    } else {
      els.previewDuration.hidden = true;
    }

    const safeThumb = sanitizeHttpUrl(info.thumbnail);
    if (safeThumb) {
      els.previewThumb.hidden = false;
      els.previewThumbFallback.hidden = true;
      els.previewThumb.src = safeThumb;
    } else {
      els.previewThumb.hidden = true;
      els.previewThumb.removeAttribute("src");
      els.previewThumbFallback.hidden = false;
    }

    els.previewCard.hidden = false;
  }

  els.previewThumb.addEventListener("error", () => {
    els.previewThumb.hidden = true;
    els.previewThumbFallback.hidden = false;
  });

  function stopPolling() {
    if (state.pollTimerId !== null) {
      clearTimeout(state.pollTimerId);
      state.pollTimerId = null;
    }
  }

  function resetJobCard() {
    stopPolling();
    state.activeJobId = null;
    els.jobCard.hidden = true;
    els.readyBox.hidden = true;
    els.cancelJobBtn.hidden = false;
    els.jobProgress.value = 0;
    els.jobPercent.textContent = "0%";
    els.saveFileLink.href = "#";
  }

  function triggerBrowserSave(downloadUrl, filename) {
    const link = document.createElement("a");
    link.href = downloadUrl;
    if (filename) {
      link.download = filename;
    }
    link.rel = "noopener";
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  function loadHistory() {
    try {
      const raw = safeStorageGet(STORAGE_KEYS.history);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  function saveHistory(items) {
    safeStorageSet(STORAGE_KEYS.history, JSON.stringify(items.slice(0, MAX_HISTORY_ITEMS)));
  }

  function addHistoryEntry(entry) {
    const items = loadHistory().filter((item) => item.url !== entry.url || item.preset !== entry.preset);
    items.unshift({
      title: String(entry.title || "Video"),
      url: sanitizeHttpUrl(entry.url) || "",
      platformLabel: String(entry.platformLabel || "Video"),
      preset: String(entry.preset || "best_mp4"),
      filesize: typeof entry.filesize === "number" ? entry.filesize : null,
      at: Date.now(),
    });
    saveHistory(items);
    renderHistory();
  }

  function renderHistory() {
    const items = loadHistory();
    els.historyList.replaceChildren();

    if (items.length === 0) {
      els.historyEmpty.hidden = false;
      els.historyList.hidden = true;
      els.clearHistoryBtn.hidden = true;
      return;
    }

    els.historyEmpty.hidden = true;
    els.historyList.hidden = false;
    els.clearHistoryBtn.hidden = false;

    for (const item of items) {
      const li = document.createElement("li");
      li.className = "history-item";

      const infoDiv = document.createElement("div");
      infoDiv.className = "history-info";

      const titleSpan = document.createElement("span");
      titleSpan.className = "history-title";
      titleSpan.textContent = item.title;

      const subSpan = document.createElement("span");
      subSpan.className = "history-sub";
      const sizeStr = formatBytes(item.filesize);
      const dateStr = new Date(item.at).toLocaleString("tr-TR", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
      subSpan.textContent = [item.platformLabel, item.preset, sizeStr, dateStr]
        .filter(Boolean)
        .join(" · ");

      infoDiv.append(titleSpan, subSpan);

      const actionsDiv = document.createElement("div");
      actionsDiv.className = "history-actions";

      const reuseBtn = document.createElement("button");
      reuseBtn.type = "button";
      reuseBtn.className = "btn btn-secondary btn-sm";
      reuseBtn.textContent = "Yükle";
      reuseBtn.addEventListener("click", () => {
        if (!item.url) return;
        els.videoUrl.value = item.url;
        els.clearBtn.hidden = false;
        updatePlatformChips(item.url);
        const radio = document.querySelector(`input[name="preset"][value="${CSS.escape(item.preset)}"]`);
        if (radio) radio.checked = true;
        els.videoUrl.focus();
      });

      actionsDiv.append(reuseBtn);
      li.append(infoDiv, actionsDiv);
      els.historyList.append(li);
    }
  }

  function renderJobSnapshot(job) {
    els.jobCard.hidden = false;
    els.jobPlatformBadge.textContent = job.platform_label || PLATFORM_LABELS[job.platform] || "Video";

    const pct = Math.max(0, Math.min(100, Math.round(Number(job.progress) || 0)));
    els.jobProgress.value = pct;
    els.jobPercent.textContent = `${pct}%`;

    if (job.status === "queued") {
      els.jobStatusTitle.textContent = "Sıraya alındı...";
      els.jobDetailText.textContent = "Sunucu indirmeyi başlatıyor...";
      els.readyBox.hidden = true;
      els.cancelJobBtn.hidden = false;
      return;
    }

    if (job.status === "downloading") {
      els.jobStatusTitle.textContent = job.title || "Video indiriliyor...";
      const parts = [];
      if (job.speed) parts.push(`Hız: ${job.speed}`);
      if (typeof job.eta === "number") parts.push(`Kalan: ${formatDuration(job.eta)}`);
      els.jobDetailText.textContent = parts.length > 0 ? parts.join(" · ") : "Akış indiriliyor...";
      els.readyBox.hidden = true;
      els.cancelJobBtn.hidden = false;
      return;
    }

    if (job.status === "processing") {
      els.jobStatusTitle.textContent = job.title || "Video & ses birleştiriliyor...";
      els.jobDetailText.textContent = "ffmpeg ile MP4/ses dönüşümü yapılıyor...";
      els.readyBox.hidden = true;
      els.cancelJobBtn.hidden = false;
      return;
    }

    if (job.status === "ready") {
      stopPolling();
      setFormBusy(false);
      els.jobStatusTitle.textContent = "İndirmeye hazır!";
      els.jobDetailText.textContent = "Tarayıcı indirmesi tetiklendi; başlamazsa aşağıdaki düğmeye dokunun.";
      els.cancelJobBtn.hidden = true;

      const fileUrl = `${state.apiUrl}/api/jobs/${encodeURIComponent(job.id)}/file?token=${encodeURIComponent(
        job.download_token || ""
      )}`;
      els.readyFilename.textContent = job.filename || "video.mp4";
      els.readyFilesize.textContent = formatBytes(job.filesize);
      els.saveFileLink.href = fileUrl;
      els.saveFileLink.download = job.filename || "video.mp4";
      els.readyBox.hidden = false;

      addHistoryEntry({
        title: job.title || job.filename,
        url: els.videoUrl.value.trim(),
        platformLabel: job.platform_label || PLATFORM_LABELS[job.platform],
        preset: job.preset,
        filesize: job.filesize,
      });

      triggerBrowserSave(fileUrl, job.filename);
      return;
    }

    if (job.status === "error" || job.status === "cancelled" || job.status === "expired") {
      stopPolling();
      setFormBusy(false);
      els.jobCard.hidden = true;
      setBanner(els.actionFeedback, job.error || "İndirme tamamlanamadı.", "error");
    }
  }

  async function pollJob(jobId) {
    if (state.activeJobId !== jobId) return;
    try {
      const job = await apiRequest(`/api/jobs/${encodeURIComponent(jobId)}`);
      if (state.activeJobId !== jobId) return;
      renderJobSnapshot(job);
      if (job.status === "queued" || job.status === "downloading" || job.status === "processing") {
        state.pollTimerId = setTimeout(() => pollJob(jobId), 1000);
      }
    } catch (err) {
      stopPolling();
      setFormBusy(false);
      if (err.status === 401) {
        setConnectionStatus("offline", "Yetkisiz");
        showAuthScreen("API anahtarınız reddedildi. Lütfen tekrar doğrulayın.", "error");
        return;
      }
      setBanner(els.actionFeedback, err.message, "error");
    }
  }

  // ---------------------------------------------------------------------------
  // Event Handlers
  // ---------------------------------------------------------------------------
  document.querySelectorAll(".toggle-secret-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = document.getElementById(btn.dataset.target);
      if (!input) return;
      const reveal = input.type === "password";
      input.type = reveal ? "text" : "password";
      btn.setAttribute("aria-pressed", reveal ? "true" : "false");
      btn.setAttribute("aria-label", reveal ? "API anahtarını gizle" : "API anahtarını göster");
      btn.textContent = reveal ? "Gizle" : "Göster";
    });
  });

  els.authForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    setBanner(els.authFeedback, "");
    if (!els.authForm.reportValidity()) return;

    const apiUrl = els.authApiUrl.value.trim();
    const apiKey = els.authApiKey.value.trim();
    els.authSubmitBtn.disabled = true;
    els.authSubmitBtn.textContent = "Doğrulanıyor...";

    try {
      await verifyCredentials(apiUrl, apiKey);
      showAppScreen();
    } catch (err) {
      setConnectionStatus("offline", "Hata");
      setBanner(els.authFeedback, err.message, "error");
    } finally {
      els.authSubmitBtn.disabled = false;
      els.authSubmitBtn.textContent = "Doğrula ve Bağlan";
    }
  });

  els.videoUrl.addEventListener("input", () => {
    const val = els.videoUrl.value.trim();
    els.clearBtn.hidden = val.length === 0;
    updatePlatformChips(val);
    setBanner(els.actionFeedback, "");
  });

  els.pasteBtn.addEventListener("click", async () => {
    if (!navigator.clipboard?.readText) {
      els.videoUrl.focus();
      setBanner(els.actionFeedback, "Tarayıcı pano erişimine izin vermiyor; bağlantıyı elle yapıştırın.", "info");
      return;
    }
    try {
      const text = (await navigator.clipboard.readText()).trim();
      if (!text) {
        setBanner(els.actionFeedback, "Panoda yapıştırılacak metin bulunamadı.", "info");
        return;
      }
      els.videoUrl.value = text;
      els.clearBtn.hidden = false;
      updatePlatformChips(text);
      setBanner(els.actionFeedback, "");
    } catch {
      els.videoUrl.focus();
      setBanner(els.actionFeedback, "Pano okunamadı. Bağlantıyı alana yapıştırın.", "info");
    }
  });

  els.clearBtn.addEventListener("click", () => {
    els.videoUrl.value = "";
    els.clearBtn.hidden = true;
    updatePlatformChips("");
    renderPreview(null);
    setBanner(els.actionFeedback, "");
    els.videoUrl.focus();
  });

  els.previewBtn.addEventListener("click", async () => {
    setBanner(els.actionFeedback, "");
    if (!els.videoUrl.reportValidity()) return;

    const url = els.videoUrl.value.trim();
    setFormBusy(true);
    els.previewBtn.textContent = "Alınıyor...";

    try {
      const data = await apiRequest("/api/info", {
        method: "POST",
        body: { url },
      });
      renderPreview(data.info);
    } catch (err) {
      if (err.status === 401) {
        setConnectionStatus("offline", "Yetkisiz");
        showAuthScreen("API anahtarınız geçersiz. Lütfen yeniden bağlanın.", "error");
        return;
      }
      setBanner(els.actionFeedback, err.message, "error");
    } finally {
      setFormBusy(false);
      els.previewBtn.textContent = "Önizle";
    }
  });

  els.downloadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    setBanner(els.actionFeedback, "");
    if (!els.downloadForm.reportValidity()) return;

    const url = els.videoUrl.value.trim();
    const selectedPreset =
      document.querySelector('input[name="preset"]:checked')?.value || "best_mp4";

    resetJobCard();
    setFormBusy(true);
    els.downloadBtn.textContent = "Başlatılıyor...";

    try {
      const job = await apiRequest("/api/jobs", {
        method: "POST",
        body: { url, preset: selectedPreset },
      });
      state.activeJobId = job.id;
      renderJobSnapshot(job);
      state.pollTimerId = setTimeout(() => pollJob(job.id), 700);
    } catch (err) {
      setFormBusy(false);
      if (err.status === 401) {
        setConnectionStatus("offline", "Yetkisiz");
        showAuthScreen("API anahtarınız geçersiz. Lütfen yeniden bağlanın.", "error");
        return;
      }
      setBanner(els.actionFeedback, err.message, "error");
    } finally {
      els.downloadBtn.textContent = "Videoyu Hazırla & İndir";
    }
  });

  els.cancelJobBtn.addEventListener("click", async () => {
    const jobId = state.activeJobId;
    resetJobCard();
    setFormBusy(false);
    if (!jobId) return;
    try {
      await apiRequest(`/api/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
    } catch {
      // Ignore cleanup errors on already-finished jobs
    }
  });

  els.dismissReadyBtn.addEventListener("click", async () => {
    const jobId = state.activeJobId;
    resetJobCard();
    if (!jobId) return;
    try {
      await apiRequest(`/api/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
    } catch {
      // Ignore cleanup errors
    }
  });

  els.clearHistoryBtn.addEventListener("click", () => {
    safeStorageRemove(STORAGE_KEYS.history);
    renderHistory();
  });

  // Settings modal handlers
  wireModalDialog(els.settingsDialog, els.closeSettingsBtn);

  els.openSettingsBtn.addEventListener("click", () => {
    els.settingsApiUrl.value = state.apiUrl;
    els.settingsApiKey.value = state.apiKey;
    setBanner(els.settingsFeedback, "");
    syncThemeUI();
    els.settingsDialog.showModal();
  });

  els.settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    setBanner(els.settingsFeedback, "");
    if (!els.settingsForm.reportValidity()) return;

    const apiUrl = els.settingsApiUrl.value.trim();
    const apiKey = els.settingsApiKey.value.trim();
    els.settingsSaveBtn.disabled = true;
    els.settingsSaveBtn.textContent = "Test ediliyor...";

    try {
      await verifyCredentials(apiUrl, apiKey);
      showAppScreen();
      setBanner(els.settingsFeedback, "Bağlantı doğrulandı ve kaydedildi.", "success");
    } catch (err) {
      setConnectionStatus("offline", "Hata");
      setBanner(els.settingsFeedback, err.message, "error");
    } finally {
      els.settingsSaveBtn.disabled = false;
      els.settingsSaveBtn.textContent = "Kaydet ve Test Et";
    }
  });

  els.disconnectBtn.addEventListener("click", async () => {
    resetJobCard();
    safeStorageRemove(STORAGE_KEYS.apiKey);
    state.apiKey = "";
    updateServerMetadata(null);
    setConnectionStatus("locked", "Kilitli");
    await closeTopLayer(els.settingsDialog);
    showAuthScreen("API anahtarı bu cihazdan silindi.", "info");
  });

  // ---------------------------------------------------------------------------
  // Bootstrap
  // ---------------------------------------------------------------------------
  async function boot() {
    syncThemeUI();
    initFormValidationA11y();
    renderHistory();

    if ("serviceWorker" in navigator) {
      const isLocal =
        window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
      if (window.location.protocol === "https:" || isLocal) {
        navigator.serviceWorker.register("./sw.js").catch(() => {});
      }
    }

    if (!state.apiKey) {
      setConnectionStatus("locked", "Kilitli");
      showAuthScreen();
      return;
    }

    try {
      setConnectionStatus("locked", "Bağlanıyor...");
      await verifyCredentials(state.apiUrl, state.apiKey);
      showAppScreen();
    } catch (err) {
      setConnectionStatus("offline", "Bağlantı Yok");
      showAuthScreen(err.message, "error");
    }
  }

  boot();
})();
