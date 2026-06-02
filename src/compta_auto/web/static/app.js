// === Tab navigation ===
const tabs = document.querySelectorAll(".tab");
const panels = document.querySelectorAll(".tab-panel");

function switchTab(tabId) {
  tabs.forEach((t) => {
    const isActive = t.dataset.tab === tabId;
    t.classList.toggle("active", isActive);
    t.setAttribute("aria-selected", isActive);
  });
  panels.forEach((p) => {
    p.classList.toggle("active", p.id === `panel-${tabId}`);
  });
  sessionStorage.setItem("compta-tab", tabId);
}

tabs.forEach((tab) => {
  tab.addEventListener("click", () => switchTab(tab.dataset.tab));
});

// Restore last active tab
const saved = sessionStorage.getItem("compta-tab");
if (saved && document.getElementById(`panel-${saved}`)) {
  switchTab(saved);
}

// === Subtab navigation ===
document.addEventListener("click", (event) => {
  const subtab = event.target.closest(".subtab");
  if (!subtab) return;

  const container = subtab.closest(".tab-panel");
  if (!container) return;

  const subtabId = subtab.dataset.subtab;
  const panelId = container.id;
  container.querySelectorAll(".subtab").forEach((st) => {
    const isActive = st.dataset.subtab === subtabId;
    st.classList.toggle("active", isActive);
    st.setAttribute("aria-selected", isActive);
  });
  container.querySelectorAll(".subtab-panel").forEach((sp) => {
    sp.classList.toggle("active", sp.id === `subpanel-${subtabId}`);
  });
  sessionStorage.setItem(`compta-subtab-${panelId}`, subtabId);
});

// Restore subtab state
document.querySelectorAll(".tab-panel").forEach((panel) => {
  const savedSubtab = sessionStorage.getItem(`compta-subtab-${panel.id}`);
  if (savedSubtab && panel.querySelector(`[data-subtab="${savedSubtab}"]`)) {
    panel.querySelectorAll(".subtab").forEach((st) => {
      const isActive = st.dataset.subtab === savedSubtab;
      st.classList.toggle("active", isActive);
      st.setAttribute("aria-selected", isActive);
    });
    panel.querySelectorAll(".subtab-panel").forEach((sp) => {
      sp.classList.toggle("active", sp.id === `subpanel-${savedSubtab}`);
    });
  }
});

// === Credentials: hide fields when saved, show edit button ===
function revealCredFields(inputIds, badgeId, editBtnId) {
  for (const id of inputIds) {
    const el = document.getElementById(id);
    if (el) el.hidden = false;
  }
  const badge = document.getElementById(badgeId);
  if (badge) badge.hidden = true;
  const editBtn = document.getElementById(editBtnId);
  if (editBtn) editBtn.hidden = true;
}

(async function loadCredentials() {
  try {
    const resp = await fetch("/api/credentials");
    if (!resp.ok) return;
    const creds = await resp.json();

    const mapping = [
      { key: "spotify_sp_dc", inputIds: ["spotify-sp-dc"], badge: "spotify-saved-badge", editBtn: "spotify-edit-btn" },
      { key: "chatgpt_bearer", inputIds: ["chatgpt-bearer"], badge: "chatgpt-saved-badge", editBtn: "chatgpt-edit-btn" },
      { key: "free_username", inputIds: ["free-username", "free-password"], badge: "free-saved-badge", editBtn: "free-edit-btn", also: "free_password" },
    ];

    for (const m of mapping) {
      const hasCred = creds[m.key]?.saved && (!m.also || creds[m.also]?.saved);
      if (!hasCred) continue;

      // Hide input fields
      for (const id of m.inputIds) {
        const el = document.getElementById(id);
        if (el) el.hidden = true;
      }
      // Show badge and edit button
      const badge = document.getElementById(m.badge);
      if (badge) {
        badge.hidden = false;
        badge.title = creds[m.key].hint;
      }
      const editBtn = document.getElementById(m.editBtn);
      if (editBtn) {
        editBtn.hidden = false;
        editBtn.addEventListener("click", () => {
          for (const id of m.inputIds) {
            const el = document.getElementById(id);
            if (el) el.hidden = false;
          }
          badge.hidden = true;
          editBtn.hidden = true;
        });
      }
    }
  } catch (e) {
    // Silently fail — fields remain visible
  }
})();
const modal = document.getElementById("preview-modal");
const modalTitle = document.getElementById("preview-modal-title");
const modalBody = document.getElementById("preview-modal-body");
const openLink = document.getElementById("preview-open-link");
const closeButton = document.getElementById("preview-close-button");
const backdrop = document.getElementById("preview-modal-backdrop");

function openModal() {
  modal.hidden = false;
  document.body.classList.add("modal-open");
  closeButton.focus();
}

function closeModal() {
  modal.hidden = true;
  document.body.classList.remove("modal-open");
  modalBody.replaceChildren();
}

function renderPreview(url, openUrl, name, kind) {
  modalTitle.textContent = name || "Attachment";
  openLink.href = openUrl || url;
  modalBody.replaceChildren();

  if (kind === "image") {
    const image = document.createElement("img");
    image.className = "preview-modal-image";
    image.src = url;
    image.alt = name;
    image.onerror = () => {
      modalBody.replaceChildren();
      const fallback = document.createElement("div");
      fallback.className = "preview-modal-fallback";
      fallback.textContent = "Preview image failed to load. Use Open to view in new window.";
      modalBody.append(fallback);
    };
    modalBody.append(image);
    return;
  }

  if (kind === "pdf") {
    const frame = document.createElement("iframe");
    frame.className = "preview-frame";
    frame.src = url;
    frame.title = name;
    modalBody.append(frame);
    return;
  }

  const fallback = document.createElement("div");
  fallback.className = "preview-modal-fallback";
  fallback.textContent = "Preview is not available for this file type.";
  modalBody.append(fallback);
}

document.addEventListener("click", (event) => {
  const trigger = event.target.closest("[data-preview-url]");
  if (!trigger) return;
  event.preventDefault();
  event.stopPropagation();
  renderPreview(
    trigger.dataset.previewUrl,
    trigger.dataset.openUrl,
    trigger.dataset.previewName,
    trigger.dataset.previewKind,
  );
  openModal();
});

closeButton.addEventListener("click", closeModal);
backdrop.addEventListener("click", closeModal);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !modal.hidden) closeModal();
});

// === Folder picker (native macOS dialog) ===
const pickFolderBtn = document.getElementById("pick-folder-btn");
const scanFolderPath = document.getElementById("scan-folder-path");
const pickFolderLabel = document.getElementById("pick-folder-label");
const scanFolderSubmit = document.getElementById("scan-folder-submit");

if (pickFolderBtn) {
  pickFolderBtn.addEventListener("click", async () => {
    pickFolderBtn.disabled = true;
    pickFolderLabel.textContent = "Opening…";
    try {
      const resp = await fetch("/api/pick-folder");
      const data = await resp.json();
      if (data.path) {
        scanFolderPath.value = data.path;
        pickFolderLabel.textContent = data.path.split("/").pop() || data.path;
        pickFolderBtn.title = data.path;
        scanFolderSubmit.disabled = false;
      } else {
        // Cancelled — restore previous label
        const prev = scanFolderPath.value;
        pickFolderLabel.textContent = prev ? prev.split("/").pop() : "Pick folder…";
      }
    } catch (e) {
      pickFolderLabel.textContent = "Error";
    } finally {
      pickFolderBtn.disabled = false;
    }
  });
}

// === Spotify fetch ===
const spotifyForm = document.getElementById("fetch-spotify-form");
if (spotifyForm) {
  spotifyForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("fetch-spotify-btn");
    const resultDiv = document.getElementById("fetch-spotify-result");
    const spDcInput = document.getElementById("spotify-sp-dc");
    const spDc = spDcInput.hidden ? "" : spDcInput.value.trim();

    // If field is visible and empty, it means no saved cred either
    if (!spDcInput.hidden && !spDc) return;

    btn.disabled = true;
    btn.textContent = "⏳ Fetching…";
    resultDiv.hidden = false;
    resultDiv.className = "fetch-result fetch-result-progress";
    resultDiv.textContent = "Connecting to Spotify…";

    try {
      const formData = new FormData();
      formData.append("sp_dc", spDc);

      const resp = await fetch("/api/fetch-spotify", { method: "POST", body: formData });

      if (!resp.ok && !resp.headers.get("content-type")?.includes("text/event-stream")) {
        const data = await resp.json();
        resultDiv.className = "fetch-result fetch-result-error";
        resultDiv.textContent = data.error || "Unknown error occurred.";
        revealCredFields(["spotify-sp-dc"], "spotify-saved-badge", "spotify-edit-btn");
        btn.disabled = false;
        btn.textContent = "🔄 Fetch invoices";
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop(); // keep incomplete line in buffer

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const event = JSON.parse(line.slice(6));

          if (event.type === "progress") {
            const pct = event.total > 0 ? Math.round((event.current / event.total) * 100) : 0;
            resultDiv.innerHTML = `<div class="fetch-progress-bar"><div class="fetch-progress-fill" style="width:${pct}%"></div></div><span>${event.message}</span>`;
          } else if (event.type === "status") {
            resultDiv.innerHTML = `<span>⏳ ${event.message}</span>`;
          } else if (event.type === "complete") {
            const r = event.result;
            const parts = [];
            if (r.downloaded > 0) parts.push(`✅ Downloaded ${r.downloaded} new invoice(s)`);
            if (r.skipped > 0) parts.push(`⏭ ${r.skipped} already present`);
            if (r.processed > 0) parts.push(`📄 ${r.processed} processed by pipeline`);
            if (r.errors && r.errors.length > 0) parts.push(`⚠️ ${r.errors.length} error(s)`);
            if (parts.length === 0) parts.push("No new invoices to download.");
            resultDiv.className = "fetch-result fetch-result-success";
            resultDiv.innerHTML = parts.join("<br>");
            // Reload page after a short delay to show new documents in the Documents tab
            if (r.downloaded > 0 || r.processed > 0) {
              setTimeout(() => { window.location.reload(); }, 2000);
            }
          } else if (event.type === "error") {
            resultDiv.className = "fetch-result fetch-result-error";
            resultDiv.textContent = event.error;
            revealCredFields(["spotify-sp-dc"], "spotify-saved-badge", "spotify-edit-btn");
          }
        }
      }
    } catch (err) {
      resultDiv.className = "fetch-result fetch-result-error";
      resultDiv.textContent = `Network error: ${err.message}`;
    } finally {
      btn.disabled = false;
      btn.textContent = "🔄 Fetch invoices";
    }
  });
}

// === ChatGPT Invoice Fetch (SSE) ===
const chatgptForm = document.getElementById("fetch-chatgpt-form");
if (chatgptForm) {
  chatgptForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("fetch-chatgpt-btn");
    const resultDiv = document.getElementById("fetch-chatgpt-result");
    const bearerInput = document.getElementById("chatgpt-bearer");
    const bearerToken = bearerInput.hidden ? "" : bearerInput.value.trim();

    if (!bearerInput.hidden && !bearerToken) return;

    btn.disabled = true;
    btn.textContent = "⏳ Fetching…";
    resultDiv.hidden = false;
    resultDiv.className = "fetch-result fetch-result-progress";
    resultDiv.textContent = "Connecting to ChatGPT…";

    try {
      const formData = new FormData();
      formData.append("bearer_token", bearerToken);

      const resp = await fetch("/api/fetch-chatgpt", { method: "POST", body: formData });

      if (!resp.ok && !resp.headers.get("content-type")?.includes("text/event-stream")) {
        const data = await resp.json();
        resultDiv.className = "fetch-result fetch-result-error";
        resultDiv.textContent = data.error || "Unknown error occurred.";
        revealCredFields(["chatgpt-bearer"], "chatgpt-saved-badge", "chatgpt-edit-btn");
        btn.disabled = false;
        btn.textContent = "🔄 Fetch invoices";
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const event = JSON.parse(line.slice(6));

          if (event.type === "progress") {
            const pct = event.total > 0 ? Math.round((event.current / event.total) * 100) : 0;
            resultDiv.innerHTML = `<div class="fetch-progress-bar"><div class="fetch-progress-fill" style="width:${pct}%"></div></div><span>${event.message}</span>`;
          } else if (event.type === "status") {
            resultDiv.innerHTML = `<span>⏳ ${event.message}</span>`;
          } else if (event.type === "complete") {
            const r = event.result;
            const parts = [];
            if (r.downloaded > 0) parts.push(`✅ Downloaded ${r.downloaded} new invoice(s)`);
            if (r.skipped > 0) parts.push(`⏭ ${r.skipped} already present`);
            if (r.processed > 0) parts.push(`📄 ${r.processed} processed by pipeline`);
            if (r.errors && r.errors.length > 0) parts.push(`⚠️ ${r.errors.length} error(s)`);
            if (parts.length === 0) parts.push("No new invoices to download.");
            resultDiv.className = "fetch-result fetch-result-success";
            resultDiv.innerHTML = parts.join("<br>");
            if (r.downloaded > 0 || r.processed > 0) {
              setTimeout(() => { window.location.reload(); }, 2000);
            }
          } else if (event.type === "error") {
            resultDiv.className = "fetch-result fetch-result-error";
            resultDiv.textContent = event.error;
            revealCredFields(["chatgpt-bearer"], "chatgpt-saved-badge", "chatgpt-edit-btn");
          }
        }
      }
    } catch (err) {
      resultDiv.className = "fetch-result fetch-result-error";
      resultDiv.textContent = `Network error: ${err.message}`;
    } finally {
      btn.disabled = false;
      btn.textContent = "🔄 Fetch invoices";
    }
  });
}

// === Free Mobile fetch (2-step: login + OTP) ===
const freeLoginForm = document.getElementById("fetch-free-login-form");
if (freeLoginForm) {
  let freeSession = {};

  freeLoginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("fetch-free-login-btn");
    const resultDiv = document.getElementById("fetch-free-result");
    const otpForm = document.getElementById("fetch-free-otp-form");
    const usernameInput = document.getElementById("free-username");
    const passwordInput = document.getElementById("free-password");
    const username = usernameInput.hidden ? "" : usernameInput.value.trim();
    const password = passwordInput.hidden ? "" : passwordInput.value;

    if (!usernameInput.hidden && (!username || !password)) return;
    btn.disabled = true;
    btn.textContent = "Logging in…";
    resultDiv.hidden = false;
    resultDiv.className = "fetch-result fetch-result-progress";
    resultDiv.textContent = "Logging in… A verification code will be sent to your email.";

    try {
      const formData = new FormData();
      formData.append("username", username);
      formData.append("password", password);
      const resp = await fetch("/api/free-mobile-login", { method: "POST", body: formData });
      const data = await resp.json();

      if (!resp.ok) {
        resultDiv.className = "fetch-result fetch-result-error";
        resultDiv.textContent = data.error || "Login failed";
        revealCredFields(["free-username", "free-password"], "free-saved-badge", "free-edit-btn");
        return;
      }

      if (data.status === "otp_required") {
        freeSession = { session_cookies: data.session_cookies, csrf_token: data.csrf_token, otp_id: data.otp_id || "" };
        resultDiv.className = "fetch-result fetch-result-progress";
        resultDiv.textContent = "✅ Code sent to your email! Enter it below.";
        otpForm.hidden = false;
        document.getElementById("free-otp").focus();
      }
    } catch (err) {
      resultDiv.className = "fetch-result fetch-result-error";
      resultDiv.textContent = `Network error: ${err.message}`;
    } finally {
      btn.disabled = false;
      btn.textContent = "🔑 Login";
    }
  });

  const otpForm = document.getElementById("fetch-free-otp-form");
  otpForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("fetch-free-otp-btn");
    const resultDiv = document.getElementById("fetch-free-result");
    const otpCode = document.getElementById("free-otp").value.trim();

    if (!otpCode || !freeSession.session_cookies) return;
    btn.disabled = true;
    btn.textContent = "Validating…";
    resultDiv.className = "fetch-result fetch-result-progress";
    resultDiv.textContent = "Validating OTP and fetching invoices…";

    try {
      const formData = new FormData();
      formData.append("session_cookies", freeSession.session_cookies);
      formData.append("csrf_token", freeSession.csrf_token);
      formData.append("otp_code", otpCode);
      formData.append("otp_id", freeSession.otp_id || "");

      const resp = await fetch("/api/free-mobile-otp", { method: "POST", body: formData });
      if (!resp.ok) {
        resultDiv.className = "fetch-result fetch-result-error";
        resultDiv.textContent = `Server error: ${resp.status}`;
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const event = JSON.parse(line.slice(6));
          if (event.type === "progress") {
            const pct = Math.round((event.current / event.total) * 100);
            resultDiv.innerHTML = `<div class="fetch-progress-bar"><div class="fetch-progress-fill" style="width:${pct}%"></div></div><span>${event.message}</span>`;
          } else if (event.type === "status") {
            resultDiv.textContent = event.message;
          } else if (event.type === "complete") {
            const r = event.result;
            resultDiv.className = "fetch-result fetch-result-success";
            let msg = `Done! ${r.downloaded} downloaded, ${r.skipped} skipped.`;
            if (r.processed) msg += ` ${r.processed} processed.`;
            if (r.message) msg += ` ${r.message}`;
            if (r.errors && r.errors.length) msg += ` (${r.errors.length} errors)`;
            resultDiv.textContent = msg;
            otpForm.hidden = true;
          } else if (event.type === "error") {
            resultDiv.className = "fetch-result fetch-result-error";
            resultDiv.textContent = event.error;
          }
        }
      }
    } catch (err) {
      resultDiv.className = "fetch-result fetch-result-error";
      resultDiv.textContent = `Network error: ${err.message}`;
    } finally {
      btn.disabled = false;
      btn.textContent = "✅ Validate & Fetch";
    }
  });
}

// === Export tab ===
const exportAllBtn = document.getElementById("export-all-btn");
const exportOutputPath = document.getElementById("export-output-path");
const exportChangeDirBtn = document.getElementById("export-change-dir-btn");
const exportResult = document.getElementById("export-result");

// Load output dir
if (exportOutputPath) {
  fetch("/api/settings/output-dir")
    .then((r) => r.json())
    .then((data) => { exportOutputPath.textContent = data.path; })
    .catch(() => {});
}

// Change output dir
if (exportChangeDirBtn) {
  exportChangeDirBtn.addEventListener("click", async () => {
    const current = exportOutputPath?.textContent || "";
    const newPath = prompt("Output directory path:", current);
    if (!newPath || newPath === current) return;
    try {
      const resp = await fetch("/api/settings/output-dir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: newPath }),
      });
      if (resp.ok) {
        exportOutputPath.textContent = newPath;
      }
    } catch (e) {
      alert("Failed to save: " + e.message);
    }
  });
}

// Export all
if (exportAllBtn) {
  exportAllBtn.addEventListener("click", async () => {
    if (!confirm("Move all included documents to the output folder?")) return;
    exportAllBtn.disabled = true;
    exportAllBtn.textContent = "⏳ Exporting…";
    exportResult.hidden = false;
    exportResult.className = "fetch-result fetch-result-progress";
    exportResult.textContent = "Moving files…";

    try {
      const resp = await fetch("/api/export", { method: "POST" });
      const data = await resp.json();
      if (data.moved > 0) {
        exportResult.className = "fetch-result fetch-result-success";
        let msg = `✅ Moved ${data.moved} file(s) to ${data.output_dir}`;
        if (data.errors.length) msg += ` (${data.errors.length} error(s))`;
        exportResult.textContent = msg;
        setTimeout(() => window.location.reload(), 1500);
      } else if (data.errors.length) {
        exportResult.className = "fetch-result fetch-result-error";
        exportResult.textContent = data.errors.join("; ");
      } else {
        exportResult.className = "fetch-result fetch-result-success";
        exportResult.textContent = "Nothing to export.";
      }
    } catch (err) {
      exportResult.className = "fetch-result fetch-result-error";
      exportResult.textContent = `Error: ${err.message}`;
    } finally {
      exportAllBtn.disabled = false;
      exportAllBtn.textContent = "🚀 Rename & move all";
    }
  });
}

// === Rename modal ===
(function() {
  const modal = document.getElementById("rename-modal");
  const backdrop = document.getElementById("rename-modal-backdrop");
  const form = document.getElementById("rename-modal-form");
  const dateInput = document.getElementById("rename-modal-date");
  const vendorInput = document.getElementById("rename-modal-vendor");
  const filenameEl = document.getElementById("rename-modal-filename");
  const closeBtn = document.getElementById("rename-close-button");
  const cancelBtn = document.getElementById("rename-cancel-button");

  function openRenameModal(docId, date, vendor, name) {
    form.action = `/documents/${docId}/rename`;
    dateInput.value = date;
    vendorInput.value = vendor;
    filenameEl.textContent = name;
    modal.hidden = false;
    dateInput.focus();
  }

  function closeRenameModal() {
    modal.hidden = true;
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".inline-rename-toggle");
    if (!btn) return;
    openRenameModal(
      btn.dataset.docId,
      btn.dataset.docDate,
      btn.dataset.docVendor,
      btn.dataset.docName
    );
  });

  backdrop.addEventListener("click", closeRenameModal);
  closeBtn.addEventListener("click", closeRenameModal);
  cancelBtn.addEventListener("click", closeRenameModal);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) closeRenameModal();
  });
})();
