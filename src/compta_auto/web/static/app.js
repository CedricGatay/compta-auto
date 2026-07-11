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

// === Wizard layout ===
const VIEW_MODE_KEY = "compta-view-mode";
const WIZARD_STEP_KEY = "compta-wizard-step";
const WIZARD_MONTH_KEY = "compta-wizard-month";
const WIZARD_STEP_TO_TAB = {
  fetch: "fetch",
  triage: "triage",
  rename: "documents",
  export: "export",
};

const viewModeButtons = document.querySelectorAll("[data-view-mode]");
const wizardShell = document.getElementById("wizard-shell");
const wizardStepButtons = document.querySelectorAll(".wizard-step");
const wizardPanels = document.querySelectorAll(".wizard-panel");
const wizardMonthInput = document.getElementById("wizard-month-input");
const wizardMonthDisplay = document.getElementById("wizard-month-display");
const wizardMonthHint = document.getElementById("wizard-month-hint");
const wizardMailContext = document.getElementById("wizard-mail-context");
const wizardStatusMail = document.getElementById("wizard-status-mail");
const scanMailForm = document.getElementById("scan-mail-form");
const scanMailMonthsInput = scanMailForm?.querySelector('input[name="months"]');

const headerHomes = {
  "scan-mail": document.querySelector('[data-header-home="scan-mail"]'),
  "scan-folder": document.querySelector('[data-header-home="scan-folder"]'),
};

const panelHomes = {
  triage: document.querySelector('[data-panel-home="triage"]'),
  documents: document.querySelector('[data-panel-home="documents"]'),
  fetch: document.querySelector('[data-panel-home="fetch"]'),
  export: document.querySelector('[data-panel-home="export"]'),
};

const wizardSlots = {
  mail: document.querySelector('[data-wizard-slot="mail"]'),
  fetch: document.querySelector('[data-wizard-slot="fetch"]'),
  folder: document.querySelector('[data-wizard-slot="folder"]'),
  triage: document.querySelector('[data-wizard-slot="triage"]'),
  rename: document.querySelector('[data-wizard-slot="rename"]'),
  export: document.querySelector('[data-wizard-slot="export"]'),
};

function moveNode(node, target) {
  if (!node || !target || node.parentElement === target) return;
  target.appendChild(node);
}

function mountWizardContent() {
  moveNode(document.getElementById("scan-mail-form"), wizardSlots.mail);
  moveNode(document.getElementById("panel-fetch"), wizardSlots.fetch);
  moveNode(document.getElementById("scan-folder-form"), wizardSlots.folder);
  moveNode(document.getElementById("panel-triage"), wizardSlots.triage);
  moveNode(document.getElementById("panel-documents"), wizardSlots.rename);
  moveNode(document.getElementById("panel-export"), wizardSlots.export);
}

function restoreClassicContent() {
  moveNode(document.getElementById("scan-mail-form"), headerHomes["scan-mail"]);
  moveNode(document.getElementById("scan-folder-form"), headerHomes["scan-folder"]);
  moveNode(document.getElementById("panel-fetch"), panelHomes.fetch);
  moveNode(document.getElementById("panel-triage"), panelHomes.triage);
  moveNode(document.getElementById("panel-documents"), panelHomes.documents);
  moveNode(document.getElementById("panel-export"), panelHomes.export);
}

function getCurrentMonthValue() {
  const today = new Date();
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
}

function getDefaultWizardMonth() {
  const date = new Date();
  date.setDate(1);
  date.setMonth(date.getMonth() - 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function parseMonthValue(value) {
  if (!/^\d{4}-\d{2}$/.test(value || "")) return null;
  const [year, month] = value.split("-").map(Number);
  return new Date(year, month - 1, 1);
}

function formatMonthValue(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function formatMonthLabel(value) {
  const parsed = parseMonthValue(value);
  if (!parsed) return "—";
  const label = new Intl.DateTimeFormat("fr-FR", { month: "long", year: "numeric" }).format(parsed);
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function shiftMonth(value, delta) {
  const parsed = parseMonthValue(value) || parseMonthValue(getDefaultWizardMonth());
  parsed.setMonth(parsed.getMonth() + delta);
  return formatMonthValue(parsed);
}

function calculateMonthsToScan(value) {
  const target = parseMonthValue(value);
  if (!target) return 1;
  const current = parseMonthValue(getCurrentMonthValue());
  const monthDelta = ((current.getFullYear() - target.getFullYear()) * 12) + (current.getMonth() - target.getMonth());
  return Math.min(24, Math.max(1, monthDelta + 1));
}

function updateWizardMonth(value) {
  if (!wizardMonthInput) return;

  const maxValue = getCurrentMonthValue();
  const normalized = (() => {
    if (!parseMonthValue(value)) return getDefaultWizardMonth();
    return value > maxValue ? maxValue : value;
  })();
  const label = formatMonthLabel(normalized);
  const monthsToScan = calculateMonthsToScan(normalized);
  const helper = monthsToScan === 1
    ? `Mail scan uses a 1-month window focused on ${label}.`
    : `Mail scan uses the last ${monthsToScan} months to fully cover ${label}.`;

  wizardMonthInput.value = normalized;
  wizardMonthDisplay.textContent = label;
  wizardMonthHint.textContent = helper;
  if (wizardMailContext) {
    wizardMailContext.textContent = `Selected month: ${label} · scan parameter: ${monthsToScan} month${monthsToScan > 1 ? "s" : ""}.`;
  }
  if (wizardStatusMail) {
    wizardStatusMail.textContent = `${label} · ${monthsToScan} month${monthsToScan > 1 ? "s" : ""} window`;
  }
  if (scanMailMonthsInput) {
    scanMailMonthsInput.value = String(monthsToScan);
    scanMailMonthsInput.title = helper;
  }
  document.querySelectorAll("[data-wizard-month-label]").forEach((element) => {
    element.textContent = label;
  });
  sessionStorage.setItem(WIZARD_MONTH_KEY, normalized);
}

function showWizardStep(stepId) {
  if (!wizardStepButtons.length) return;
  const resolvedStep = Array.from(wizardStepButtons).some((button) => button.dataset.wizardStep === stepId)
    ? stepId
    : wizardStepButtons[0].dataset.wizardStep;

  wizardStepButtons.forEach((button) => {
    const isActive = button.dataset.wizardStep === resolvedStep;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-selected", isActive);
  });

  wizardPanels.forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.wizardPanel === resolvedStep);
  });

  const tabTarget = WIZARD_STEP_TO_TAB[resolvedStep];
  if (tabTarget) switchTab(tabTarget);
  sessionStorage.setItem(WIZARD_STEP_KEY, resolvedStep);
}

function setViewMode(mode) {
  const resolvedMode = mode === "classic" ? "classic" : "wizard";
  const currentWizardStep = document.querySelector(".wizard-step.active")?.dataset.wizardStep || sessionStorage.getItem(WIZARD_STEP_KEY) || "mail";

  if (resolvedMode === "wizard") {
    mountWizardContent();
    document.body.classList.add("view-wizard");
    document.body.classList.remove("view-classic");
    showWizardStep(sessionStorage.getItem(WIZARD_STEP_KEY) || "mail");
  } else {
    restoreClassicContent();
    document.body.classList.add("view-classic");
    document.body.classList.remove("view-wizard");
    switchTab(WIZARD_STEP_TO_TAB[currentWizardStep] || sessionStorage.getItem("compta-tab") || "triage");
  }

  viewModeButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.viewMode === resolvedMode);
  });
  sessionStorage.setItem(VIEW_MODE_KEY, resolvedMode);
}

if (wizardShell) {
  if (wizardMonthInput) {
    wizardMonthInput.max = getCurrentMonthValue();
    updateWizardMonth(sessionStorage.getItem(WIZARD_MONTH_KEY) || getDefaultWizardMonth());

    document.querySelectorAll("[data-month-shift]").forEach((button) => {
      button.addEventListener("click", () => {
        updateWizardMonth(shiftMonth(wizardMonthInput.value, Number(button.dataset.monthShift || 0)));
      });
    });
    wizardMonthInput.addEventListener("change", () => updateWizardMonth(wizardMonthInput.value));
  }

  wizardStepButtons.forEach((button) => {
    button.addEventListener("click", () => showWizardStep(button.dataset.wizardStep));
  });
  document.querySelectorAll(".wizard-next-btn").forEach((button) => {
    button.addEventListener("click", () => showWizardStep(button.dataset.nextStep));
  });
  viewModeButtons.forEach((button) => {
    button.addEventListener("click", () => setViewMode(button.dataset.viewMode));
  });

  setViewMode(sessionStorage.getItem(VIEW_MODE_KEY) || "wizard");
}

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
      { key: "orange_username", inputIds: ["orange-username", "orange-password"], badge: "orange-saved-badge", editBtn: "orange-edit-btn", also: "orange_password" },
      { key: "sosh_username", inputIds: ["sosh-username", "sosh-password"], badge: "sosh-saved-badge", editBtn: "sosh-edit-btn", also: "sosh_password" },
      { key: "freebox_username", inputIds: ["freebox-username", "freebox-password"], badge: "freebox-saved-badge", editBtn: "freebox-edit-btn", also: "freebox_password" },
      { key: "ovh_app_key", inputIds: ["ovh-app-key", "ovh-app-secret", "ovh-consumer-key"], badge: "ovh-saved-badge", editBtn: "ovh-edit-btn", also: "ovh_app_secret" },
      { key: "engie_email", inputIds: ["engie-email", "engie-password"], badge: "engie-saved-badge", editBtn: "engie-edit-btn", also: "engie_password" },
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

// === Async scan helpers (SSE-based) ===
async function runScanSSE(url, formData, btn, resultDiv, formatProgress, formatComplete) {
  btn.disabled = true;
  const origText = btn.textContent;
  btn.textContent = "⏳ Scanning…";
  resultDiv.hidden = false;
  resultDiv.className = "scan-result scan-result-progress";
  resultDiv.textContent = "Starting…";

  try {
    const resp = await fetch(url, { method: "POST", body: formData });
    if (!resp.ok && !resp.headers.get("content-type")?.includes("text/event-stream")) {
      const data = await resp.json();
      resultDiv.className = "scan-result scan-result-error";
      resultDiv.textContent = data.detail || "Error";
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

        if (event.type === "status") {
          resultDiv.innerHTML = `<span>⏳ ${event.message}</span>`;
        } else if (event.type === "start") {
          resultDiv.innerHTML = `<span>⏳ Found ${event.total} items…</span>`;
        } else if (event.type === "progress") {
          const pct = event.total > 0 ? Math.round((event.current / event.total) * 100) : 0;
          resultDiv.innerHTML = `<div class="fetch-progress-bar"><div class="fetch-progress-fill" style="width:${pct}%"></div></div><span>${formatProgress(event)}</span>`;
        } else if (event.type === "complete") {
          resultDiv.className = "scan-result scan-result-success";
          resultDiv.innerHTML = formatComplete(event.result);
          // Auto-refresh panels after scan completes
          setTimeout(() => refreshDocumentsPanel(), 300);
        } else if (event.type === "error") {
          resultDiv.className = "scan-result scan-result-error";
          resultDiv.textContent = event.error;
        }
      }
    }
  } catch (err) {
    resultDiv.className = "scan-result scan-result-error";
    resultDiv.textContent = `Network error: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = origText;
  }
}

// Mail scan form
if (scanMailForm) {
  scanMailForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const btn = document.getElementById("scan-mail-btn");
    const resultDiv = document.getElementById("scan-mail-result");
    const formData = new FormData(scanMailForm);
    runScanSSE("/scan", formData, btn, resultDiv,
      (ev) => `${ev.current}/${ev.total} threads · ${ev.new || 0} new · ${ev.triage || 0} triage`,
      (r) => {
        const parts = [];
        parts.push(`✅ Scanned ${r.scanned_messages} messages`);
        if (r.new_mails) parts.push(`📬 ${r.new_mails} new`);
        if (r.triage_mails) parts.push(`📋 ${r.triage_mails} triage`);
        if (r.attachments_extracted) parts.push(`📎 ${r.attachments_extracted} attachments`);
        return parts.join(" · ");
      }
    );
  });
}

// Folder scan form
const scanFolderForm = document.getElementById("scan-folder-form");
if (scanFolderForm) {
  scanFolderForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const btn = document.getElementById("scan-folder-submit");
    const resultDiv = document.getElementById("scan-folder-result");
    const formData = new FormData(scanFolderForm);
    runScanSSE("/scan-folder", formData, btn, resultDiv,
      (ev) => `${ev.current}/${ev.total} files · ${ev.renamed || 0} renamed · ${ev.review || 0} review`,
      (r) => {
        const parts = [];
        parts.push(`✅ Scanned ${r.scanned_messages} files`);
        if (r.renamed) parts.push(`📄 ${r.renamed} renamed`);
        if (r.rename_review_needed) parts.push(`📋 ${r.rename_review_needed} need review`);
        if (r.duplicates_skipped) parts.push(`⏭ ${r.duplicates_skipped} duplicates`);
        return parts.join(" · ");
      }
    );
  });
}

// === Global fetch lock — prevent concurrent fetches ===
let fetchInProgress = false;
let fetchInProgressProvider = "";
const ALL_FETCH_BTNS = [
  "fetch-spotify-btn", "fetch-chatgpt-btn", "fetch-free-login-btn", "fetch-free-otp-btn", "fetch-free-auto-btn",
  "fetch-orange-btn", "fetch-sosh-btn", "fetch-freebox-btn", "fetch-ovh-btn", "fetch-henrri-btn",
  "fetch-engie-login-btn", "fetch-engie-otp-btn", "fetch-engie-auto-btn",
  "inqom-upload-btn"
];

function acquireFetchLock(providerName) {
  if (fetchInProgress) return false;
  fetchInProgress = true;
  fetchInProgressProvider = providerName;
  // Disable all other fetch buttons
  for (const id of ALL_FETCH_BTNS) {
    const el = document.getElementById(id);
    if (el) el.disabled = true;
  }
  return true;
}

function releaseFetchLock() {
  fetchInProgress = false;
  fetchInProgressProvider = "";
  // Re-enable all fetch buttons
  for (const id of ALL_FETCH_BTNS) {
    const el = document.getElementById(id);
    if (el) el.disabled = false;
  }
}

// === Generic provider SSE fetch ===
// Reads an SSE stream from a provider endpoint and updates the UI.
// `onComplete` is optional; defaults to standard invoice result formatting.
function readProviderSSE(resp, resultDiv, { credFields, badgeId, editBtnId, onComplete, onDone }) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  function formatDefaultComplete(r) {
    const parts = [];
    if (r.downloaded > 0) parts.push(`✅ Downloaded ${r.downloaded} new invoice(s)`);
    if (r.skipped > 0) parts.push(`⏭ ${r.skipped} already present`);
    if (r.processed > 0) parts.push(`📄 ${r.processed} processed by pipeline`);
    if (r.errors && r.errors.length > 0) parts.push(`⚠️ ${r.errors.length} error(s)`);
    if (parts.length === 0) parts.push("No new invoices to download.");
    return parts.join("<br>");
  }

  return (async () => {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        let event;
        try {
          event = JSON.parse(line.slice(6));
        } catch (err) {
          resultDiv.className = "fetch-result fetch-result-error";
          resultDiv.textContent = `Invalid server event: ${err.message}`;
          return;
        }
        if (event.type === "progress") {
          const pct = event.total > 0 ? Math.round((event.current / event.total) * 100) : 0;
          resultDiv.innerHTML = `<div class="fetch-progress-bar"><div class="fetch-progress-fill" style="width:${pct}%"></div></div><span>${event.message}</span>`;
        } else if (event.type === "status") {
          resultDiv.innerHTML = `<span>⏳ ${event.message}</span>`;
        } else if (event.type === "uploaded") {
          const pct = event.total > 0 ? Math.round((event.current / event.total) * 100) : 0;
          resultDiv.innerHTML = `<div class="fetch-progress-bar"><div class="fetch-progress-fill" style="width:${pct}%"></div></div><span>Uploaded ${event.file || "document"} (${event.current}/${event.total})</span>`;
        } else if (event.type === "complete" || event.type === "done") {
          const r = event.result || event;
          resultDiv.className = "fetch-result fetch-result-success";
          if (onComplete) {
            onComplete(r, resultDiv);
          } else {
            resultDiv.innerHTML = formatDefaultComplete(r);
            if (r.downloaded > 0 || r.processed > 0) {
              resultDiv.innerHTML += '<br><a href="/" class="btn btn-outline btn-sm" style="margin-top:8px">🔄 Refresh to see new documents</a>';
            }
          }
          if (onDone) onDone(r);
        } else if (event.type === "error") {
          resultDiv.className = "fetch-result fetch-result-error";
          resultDiv.textContent = event.error;
          if (credFields) revealCredFields(credFields, badgeId, editBtnId);
          return;
        }
      }
    }
  })();
}

// Standard complete handler used by most providers (compact text format)
function formatCompactComplete(r, resultDiv) {
  let msg = `Done! ${r.downloaded} downloaded, ${r.skipped} skipped.`;
  if (r.processed) msg += ` ${r.processed} processed.`;
  if (r.message) msg += ` ${r.message}`;
  if (r.errors && r.errors.length) msg += ` (${r.errors.length} errors)`;
  resultDiv.textContent = msg;
}

// Bind a single-step provider fetch form (credentials → POST → SSE stream)
function bindProviderFetch({ formId, btnId, resultId, providerName, endpoint, btnLabel, connectingMsg, credInputIds, badgeId, editBtnId, buildFormData }) {
  const form = document.getElementById(formId);
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!acquireFetchLock(providerName)) return;
    const btn = document.getElementById(btnId);
    const resultDiv = document.getElementById(resultId);

    // Gather credentials; skip if hidden (already saved)
    const creds = {};
    let hasVisible = false;
    let allFilled = true;
    for (const id of credInputIds) {
      const el = document.getElementById(id);
      if (!el.hidden) {
        hasVisible = true;
        if (!el.value.trim()) allFilled = false;
        creds[id] = el.value.trim();
      } else {
        creds[id] = "";
      }
    }
    if (hasVisible && !allFilled) return;

    btn.disabled = true;
    btn.textContent = "⏳ Fetching…";
    resultDiv.hidden = false;
    resultDiv.className = "fetch-result fetch-result-progress";
    resultDiv.textContent = connectingMsg;

    try {
      const formData = buildFormData(creds);
      const resp = await fetch(endpoint, { method: "POST", body: formData });

      if (!resp.ok && !resp.headers.get("content-type")?.includes("text/event-stream")) {
        const data = await resp.json();
        resultDiv.className = "fetch-result fetch-result-error";
        resultDiv.textContent = data.error || `Server error: ${resp.status}`;
        revealCredFields(credInputIds, badgeId, editBtnId);
        return;
      }

      await readProviderSSE(resp, resultDiv, { credFields: credInputIds, badgeId, editBtnId });
    } catch (err) {
      resultDiv.className = "fetch-result fetch-result-error";
      resultDiv.textContent = `Network error: ${err.message}`;
    } finally {
      releaseFetchLock();
      btn.disabled = false;
      btn.textContent = btnLabel;
    }
  });
}

// === Spotify fetch ===
bindProviderFetch({
  formId: "fetch-spotify-form", btnId: "fetch-spotify-btn", resultId: "fetch-spotify-result",
  providerName: "Spotify", endpoint: "/api/fetch-spotify", btnLabel: "🔄 Fetch invoices",
  connectingMsg: "Connecting to Spotify…",
  credInputIds: ["spotify-sp-dc"], badgeId: "spotify-saved-badge", editBtnId: "spotify-edit-btn",
  buildFormData: (creds) => { const fd = new FormData(); fd.append("sp_dc", creds["spotify-sp-dc"]); return fd; },
});

// === ChatGPT fetch ===
bindProviderFetch({
  formId: "fetch-chatgpt-form", btnId: "fetch-chatgpt-btn", resultId: "fetch-chatgpt-result",
  providerName: "ChatGPT", endpoint: "/api/fetch-chatgpt", btnLabel: "🔄 Fetch invoices",
  connectingMsg: "Connecting to ChatGPT…",
  credInputIds: ["chatgpt-bearer"], badgeId: "chatgpt-saved-badge", editBtnId: "chatgpt-edit-btn",
  buildFormData: (creds) => { const fd = new FormData(); fd.append("bearer_token", creds["chatgpt-bearer"]); return fd; },
});

// === Orange fetch ===
bindProviderFetch({
  formId: "fetch-orange-form", btnId: "fetch-orange-btn", resultId: "fetch-orange-result",
  providerName: "Orange", endpoint: "/api/orange-fetch", btnLabel: "📥 Fetch Invoices",
  connectingMsg: "Launching browser and authenticating… (15-30s)",
  credInputIds: ["orange-username", "orange-password"], badgeId: "orange-saved-badge", editBtnId: "orange-edit-btn",
  buildFormData: (creds) => { const fd = new FormData(); fd.append("username", creds["orange-username"]); fd.append("password", creds["orange-password"]); return fd; },
});

// === Sosh fetch ===
bindProviderFetch({
  formId: "fetch-sosh-form", btnId: "fetch-sosh-btn", resultId: "fetch-sosh-result",
  providerName: "Sosh", endpoint: "/api/sosh-fetch", btnLabel: "📥 Fetch Invoices",
  connectingMsg: "Launching browser and authenticating… (15-30s)",
  credInputIds: ["sosh-username", "sosh-password"], badgeId: "sosh-saved-badge", editBtnId: "sosh-edit-btn",
  buildFormData: (creds) => { const fd = new FormData(); fd.append("username", creds["sosh-username"]); fd.append("password", creds["sosh-password"]); return fd; },
});

// === Freebox fetch ===
bindProviderFetch({
  formId: "fetch-freebox-form", btnId: "fetch-freebox-btn", resultId: "fetch-freebox-result",
  providerName: "Freebox", endpoint: "/api/freebox-fetch", btnLabel: "📥 Fetch Invoices",
  connectingMsg: "Logging in to Freebox subscriber portal…",
  credInputIds: ["freebox-username", "freebox-password"], badgeId: "freebox-saved-badge", editBtnId: "freebox-edit-btn",
  buildFormData: (creds) => { const fd = new FormData(); fd.append("username", creds["freebox-username"]); fd.append("password", creds["freebox-password"]); return fd; },
});

// === OVH fetch ===
bindProviderFetch({
  formId: "fetch-ovh-form", btnId: "fetch-ovh-btn", resultId: "fetch-ovh-result",
  providerName: "OVH", endpoint: "/api/ovh-fetch", btnLabel: "📥 Fetch Invoices",
  connectingMsg: "Connecting to OVH API…",
  credInputIds: ["ovh-app-key", "ovh-app-secret", "ovh-consumer-key"], badgeId: "ovh-saved-badge", editBtnId: "ovh-edit-btn",
  buildFormData: (creds) => { const fd = new FormData(); fd.append("app_key", creds["ovh-app-key"]); fd.append("app_secret", creds["ovh-app-secret"]); fd.append("consumer_key", creds["ovh-consumer-key"]); return fd; },
});

// === Henrri fetch ===
bindProviderFetch({
  formId: "fetch-henrri-form", btnId: "fetch-henrri-btn", resultId: "fetch-henrri-result",
  providerName: "Henrri", endpoint: "/api/henrri-fetch", btnLabel: "📥 Fetch Invoices",
  connectingMsg: "Connecting to Henrri API…",
  credInputIds: ["henrri-client-id", "henrri-client-secret"], badgeId: "henrri-saved-badge", editBtnId: "henrri-edit-btn",
  buildFormData: (creds) => { const fd = new FormData(); fd.append("client_id", creds["henrri-client-id"]); fd.append("client_secret", creds["henrri-client-secret"]); return fd; },
});

// === Free Mobile fetch (2-step: login + OTP) ===
const freeLoginForm = document.getElementById("fetch-free-login-form");
if (freeLoginForm) {
  let freeSession = {};

  freeLoginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!acquireFetchLock("Free Mobile")) return;
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
        releaseFetchLock();
        return;
      }

      if (data.status === "otp_required") {
        freeSession = { session_cookies: data.session_cookies, csrf_token: data.csrf_token, otp_id: data.otp_id || "" };
        resultDiv.className = "fetch-result fetch-result-progress";
        resultDiv.textContent = "✅ Code sent to your email! Enter it below.";
        otpForm.hidden = false;
        document.getElementById("fetch-free-otp-btn").disabled = false;
        document.getElementById("free-otp").focus();
      }
    } catch (err) {
      resultDiv.className = "fetch-result fetch-result-error";
      resultDiv.textContent = `Network error: ${err.message}`;
      releaseFetchLock();
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

      await readProviderSSE(resp, resultDiv, {
        onComplete: (r, div) => { formatCompactComplete(r, div); otpForm.hidden = true; },
      });
    } catch (err) {
      resultDiv.className = "fetch-result fetch-result-error";
      resultDiv.textContent = `Network error: ${err.message}`;
    } finally {
      releaseFetchLock();
      btn.disabled = false;
      btn.textContent = "✅ Validate & Fetch";
    }
  });
}

// === Engie Pro fetch (2-step: login + OTP) ===
const engieLoginForm = document.getElementById("fetch-engie-login-form");
if (engieLoginForm) {
  engieLoginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!acquireFetchLock("Engie Pro")) return;
    const btn = document.getElementById("fetch-engie-login-btn");
    const resultDiv = document.getElementById("fetch-engie-result");
    const emailInput = document.getElementById("engie-email");
    const passwordInput = document.getElementById("engie-password");
    const email = emailInput.hidden ? "" : emailInput.value.trim();
    const password = passwordInput.hidden ? "" : passwordInput.value;

    if (!emailInput.hidden && (!email || !password)) return;
    btn.disabled = true;
    btn.textContent = "Logging in…";
    resultDiv.hidden = false;
    resultDiv.className = "fetch-result fetch-result-progress";
    resultDiv.textContent = "Authenticating…";

    try {
      const formData = new FormData();
      formData.append("email", email);
      formData.append("password", password);
      const resp = await fetch("/api/engie-login", { method: "POST", body: formData });
      const data = await resp.json();

      if (!resp.ok) {
        resultDiv.className = "fetch-result fetch-result-error";
        resultDiv.textContent = data.error || `Server error: ${resp.status}`;
        revealCredFields(["engie-email", "engie-password"], "engie-saved-badge", "engie-edit-btn");
        releaseFetchLock();
        return;
      }

      if (data.status === "otp_required") {
        document.getElementById("engie-session-cookies").value = data.session_cookies;
        document.getElementById("engie-factor-id").value = data.factor_id;
        document.getElementById("engie-user-id").value = data.user_id;
        document.getElementById("engie-form-build-id").value = data.form_build_id;
        document.getElementById("fetch-engie-otp-form").hidden = false;
        document.getElementById("fetch-engie-otp-btn").disabled = false;
        resultDiv.className = "fetch-result fetch-result-progress";
        resultDiv.textContent = "Security code sent to your email. Enter it below.";
        document.getElementById("engie-otp-code").focus();
      } else {
        resultDiv.className = "fetch-result fetch-result-success";
        resultDiv.textContent = "Logged in without MFA (device trusted).";
      }
    } catch (err) {
      resultDiv.className = "fetch-result fetch-result-error";
      resultDiv.textContent = `Network error: ${err.message}`;
      releaseFetchLock();
    } finally {
      btn.disabled = false;
      btn.textContent = "🔐 Login";
    }
  });
}

const engieOtpForm = document.getElementById("fetch-engie-otp-form");
if (engieOtpForm) {
  engieOtpForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("fetch-engie-otp-btn");
    const resultDiv = document.getElementById("fetch-engie-result");
    const otpCode = document.getElementById("engie-otp-code").value.trim();
    if (!otpCode || otpCode.length !== 6) return;

    btn.disabled = true;
    btn.textContent = "Validating…";
    resultDiv.className = "fetch-result fetch-result-progress";
    resultDiv.textContent = "Validating code and fetching invoices…";

    try {
      const formData = new FormData();
      formData.append("session_cookies", document.getElementById("engie-session-cookies").value);
      formData.append("factor_id", document.getElementById("engie-factor-id").value);
      formData.append("user_id", document.getElementById("engie-user-id").value);
      formData.append("form_build_id", document.getElementById("engie-form-build-id").value);
      formData.append("otp_code", otpCode);
      const resp = await fetch("/api/engie-otp", { method: "POST", body: formData });
      if (!resp.ok) {
        const data = await resp.json();
        resultDiv.className = "fetch-result fetch-result-error";
        resultDiv.textContent = data.error || `Server error: ${resp.status}`;
        return;
      }

      await readProviderSSE(resp, resultDiv, {
        onComplete: (r, div) => { formatCompactComplete(r, div); document.getElementById("fetch-engie-otp-form").hidden = true; },
      });
    } catch (err) {
      resultDiv.className = "fetch-result fetch-result-error";
      resultDiv.textContent = `Network error: ${err.message}`;
    } finally {
      releaseFetchLock();
      btn.disabled = false;
      btn.textContent = "📥 Validate & Fetch";
    }
  });
}

// === Free Mobile auto-fetch (single-step via mailbox OTP) ===
const freeAutoBtn = document.getElementById("fetch-free-auto-btn");
if (freeAutoBtn) {
  freeAutoBtn.addEventListener("click", async () => {
    if (!acquireFetchLock("Free Mobile Auto")) return;
    const resultDiv = document.getElementById("fetch-free-result");
    const usernameInput = document.getElementById("free-username");
    const passwordInput = document.getElementById("free-password");
    const username = usernameInput.hidden ? "" : usernameInput.value.trim();
    const password = passwordInput.hidden ? "" : passwordInput.value;

    freeAutoBtn.disabled = true;
    freeAutoBtn.textContent = "⏳ Auto-fetching…";
    resultDiv.hidden = false;
    resultDiv.className = "fetch-result fetch-result-progress";
    resultDiv.textContent = "Logging in and waiting for OTP from mailbox…";

    try {
      const formData = new FormData();
      formData.append("username", username);
      formData.append("password", password);
      const resp = await fetch("/api/free-mobile-auto", { method: "POST", body: formData });
      if (!resp.ok) {
        const data = await resp.json();
        resultDiv.className = "fetch-result fetch-result-error";
        resultDiv.textContent = data.error || `Server error: ${resp.status}`;
        return;
      }
      await readProviderSSE(resp, resultDiv, {
        onComplete: (r, div) => { formatCompactComplete(r, div); },
      });
    } catch (err) {
      resultDiv.className = "fetch-result fetch-result-error";
      resultDiv.textContent = `Network error: ${err.message}`;
    } finally {
      releaseFetchLock();
      freeAutoBtn.disabled = false;
      freeAutoBtn.textContent = "🤖 Auto-fetch";
    }
  });
}

// === Engie Pro auto-fetch (single-step via mailbox OTP) ===
const engieAutoBtn = document.getElementById("fetch-engie-auto-btn");
if (engieAutoBtn) {
  engieAutoBtn.addEventListener("click", async () => {
    if (!acquireFetchLock("Engie Pro Auto")) return;
    const resultDiv = document.getElementById("fetch-engie-result");
    const emailInput = document.getElementById("engie-email");
    const passwordInput = document.getElementById("engie-password");
    const email = emailInput.hidden ? "" : emailInput.value.trim();
    const password = passwordInput.hidden ? "" : passwordInput.value;

    engieAutoBtn.disabled = true;
    engieAutoBtn.textContent = "⏳ Auto-fetching…";
    resultDiv.hidden = false;
    resultDiv.className = "fetch-result fetch-result-progress";
    resultDiv.textContent = "Logging in and waiting for OTP from mailbox…";

    try {
      const formData = new FormData();
      formData.append("email", email);
      formData.append("password", password);
      const resp = await fetch("/api/engie-auto", { method: "POST", body: formData });
      if (!resp.ok) {
        const data = await resp.json();
        resultDiv.className = "fetch-result fetch-result-error";
        resultDiv.textContent = data.error || `Server error: ${resp.status}`;
        return;
      }
      await readProviderSSE(resp, resultDiv, {
        onComplete: (r, div) => { formatCompactComplete(r, div); document.getElementById("fetch-engie-otp-form").hidden = true; },
      });
    } catch (err) {
      resultDiv.className = "fetch-result fetch-result-error";
      resultDiv.textContent = `Network error: ${err.message}`;
    } finally {
      releaseFetchLock();
      engieAutoBtn.disabled = false;
      engieAutoBtn.textContent = "🤖 Auto-fetch";
    }
  });
}

// === Export tab ===
function loadExportOutputPath() {
  const exportOutputPath = document.getElementById("export-output-path");
  if (!exportOutputPath) return;
  fetch("/api/settings/output-dir")
    .then((r) => r.json())
    .then((data) => { exportOutputPath.textContent = data.path; })
    .catch(() => {});
}

loadExportOutputPath();

function formatInqomComplete(result, resultDiv) {
  const parts = [];
  const errors = Array.isArray(result.errors) ? result.errors : [];
  if (result.total > 0 && result.uploaded === result.total && errors.length === 0) {
    parts.push("✅ All documents uploaded to Inqom");
  }
  if (result.message) parts.push(result.message);
  if (typeof result.uploaded === "number" && !parts.length) parts.push(`✅ Uploaded ${result.uploaded} document(s)`);
  if (typeof result.skipped === "number" && result.skipped > 0) parts.push(`⏭ ${result.skipped} skipped`);
  if (typeof result.failed === "number" && result.failed > 0) parts.push(`⚠️ ${result.failed} failed`);
  if (errors.length > 0) parts.push(`⚠️ ${errors.length} error(s)`);
  if (!parts.length) parts.push("Upload complete.");
  resultDiv.innerHTML = parts.join("<br>");
}

document.addEventListener("click", async (e) => {
  const changeDirBtn = e.target.closest("#export-change-dir-btn");
  if (changeDirBtn) {
    const exportOutputPath = document.getElementById("export-output-path");
    const current = exportOutputPath?.textContent || "";
    const newPath = prompt("Output directory path:", current);
    if (!newPath || newPath === current) return;
    try {
      const resp = await fetch("/api/settings/output-dir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: newPath }),
      });
      if (resp.ok && exportOutputPath) {
        exportOutputPath.textContent = newPath;
      }
    } catch (err) {
      alert("Failed to save: " + err.message);
    }
    return;
  }

  const exportAllBtn = e.target.closest("#export-all-btn");
  if (exportAllBtn) {
    const exportResult = document.getElementById("export-result");
    if (!exportResult) return;
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
        exportResult.innerHTML = msg + '<br><a href="/" class="btn btn-outline btn-sm" style="margin-top:8px">🔄 Refresh</a>';
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
      exportAllBtn.textContent = exportAllBtn.dataset.defaultLabel || "🚀 Rename & move all";
    }
    return;
  }

  const inqomUploadBtn = e.target.closest("#inqom-upload-btn");
  if (!inqomUploadBtn) return;
  const resultDiv = document.getElementById("inqom-upload-result");
  if (!resultDiv) return;
  if (!acquireFetchLock("Inqom")) return;

  inqomUploadBtn.disabled = true;
  inqomUploadBtn.textContent = "⏳ Uploading…";
  resultDiv.hidden = false;
  resultDiv.className = "fetch-result fetch-result-progress";
  resultDiv.textContent = "Starting Inqom upload…";

  try {
    const resp = await fetch("/api/inqom-upload", { method: "POST" });
    if (!resp.ok && !resp.headers.get("content-type")?.includes("text/event-stream")) {
      let message = `Server error: ${resp.status}`;
      try {
        const data = await resp.json();
        message = data.error || data.message || message;
      } catch {
        const text = await resp.text();
        if (text) message = text;
      }
      throw new Error(message);
    }
    await readProviderSSE(resp, resultDiv, {
      onComplete: formatInqomComplete,
      onDone: () => setTimeout(() => refreshDocumentsPanel(), 400),
    });
  } catch (err) {
    resultDiv.className = "fetch-result fetch-result-error";
    resultDiv.textContent = `Error: ${err.message}`;
  } finally {
    releaseFetchLock();
    inqomUploadBtn.disabled = false;
    inqomUploadBtn.textContent = "☁️ Upload to Inqom";
  }
});

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

// === PDF Preview modal ===
(function() {
  const modal = document.getElementById("pdf-preview-modal");
  const backdrop = document.getElementById("pdf-preview-backdrop");
  const frame = document.getElementById("pdf-preview-frame");
  const titleEl = document.getElementById("pdf-preview-title");
  const saveForm = document.getElementById("pdf-preview-save-form");
  const closeBtn = document.getElementById("pdf-preview-close");
  const cancelBtn = document.getElementById("pdf-preview-cancel");

  function open(mailId, subject) {
    frame.src = `/mails/${mailId}/pdf-preview`;
    titleEl.textContent = `PDF Preview — ${subject}`;
    saveForm.dataset.action = `/mails/${mailId}/to-pdf`;
    modal.hidden = false;
  }

  function close() {
    modal.hidden = true;
    frame.src = "about:blank";
  }

  // Async form submission — close modal immediately, process in background
  saveForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = saveForm.dataset.action;
    const btn = saveForm.querySelector("button[type=submit]");
    btn.disabled = true;
    btn.textContent = "⏳ Processing…";
    close();
    try {
      await fetch(url, { method: "POST", redirect: "manual" });
    } catch (_) { /* ignore network errors */ }
    btn.disabled = false;
    btn.textContent = "✓ Process & save document";
    setTimeout(() => refreshDocumentsPanel(), 300);
  });

  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".mail-to-pdf-btn");
    if (!btn) return;
    open(btn.dataset.mailId, btn.dataset.mailSubject);
  });

  backdrop.addEventListener("click", close);
  closeBtn.addEventListener("click", close);
  cancelBtn.addEventListener("click", close);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) close();
  });
})();

// === Shared panel refresh ===
async function dismissProviderHandler() {
  const btn = this;
  const vendor = btn.dataset.vendor;
  const card = btn.closest(".missing-provider-card");
  const formData = new FormData();
  formData.append("vendor", vendor);
  await fetch("/api/dismiss-provider-suggestion", { method: "POST", body: formData });
  card.style.transition = "opacity 0.2s, transform 0.2s";
  card.style.opacity = "0";
  card.style.transform = "scale(0.95)";
  setTimeout(() => {
    card.remove();
    const section = document.querySelector(".missing-providers-section");
    if (section && !section.querySelector(".missing-provider-card")) {
      section.remove();
    }
  }, 200);
}

async function refreshDocumentsPanel() {
  const scrollY = window.scrollY;
  const html = await (await fetch("/", {headers: {"Accept": "text/html"}})).text();
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, "text/html");
  const freshPanel = doc.getElementById("panel-documents");
  const currentPanel = document.getElementById("panel-documents");
  if (freshPanel && currentPanel) currentPanel.innerHTML = freshPanel.innerHTML;
  // Also refresh export panel (documents move between panels)
  const freshExport = doc.getElementById("panel-export");
  const currentExport = document.getElementById("panel-export");
  if (freshExport && currentExport) currentExport.innerHTML = freshExport.innerHTML;
  loadExportOutputPath();
  // Refresh triage panel
  const freshTriage = doc.getElementById("panel-triage");
  const currentTriage = document.getElementById("panel-triage");
  if (freshTriage && currentTriage) currentTriage.innerHTML = freshTriage.innerHTML;
  // Refresh fetch panel badges and missing providers (without replacing forms)
  const freshFetch = doc.getElementById("panel-fetch");
  const currentFetch = document.getElementById("panel-fetch");
  if (freshFetch && currentFetch) {
    // Update provider hint badges by data attribute
    freshFetch.querySelectorAll("[data-provider-hint]").forEach(freshBadge => {
      const key = freshBadge.dataset.providerHint;
      const currentBadge = currentFetch.querySelector(`[data-provider-hint="${key}"]`);
      if (currentBadge) {
        currentBadge.textContent = freshBadge.textContent;
        currentBadge.hidden = freshBadge.hidden;
      }
    });
    // Replace missing providers section
    const freshMissing = freshFetch.querySelector(".missing-providers-section");
    const currentMissing = currentFetch.querySelector(".missing-providers-section");
    if (freshMissing && currentMissing) {
      currentMissing.replaceWith(freshMissing.cloneNode(true));
    } else if (freshMissing && !currentMissing) {
      const h2 = currentFetch.querySelector("h2");
      if (h2) h2.insertAdjacentElement("afterend", freshMissing.cloneNode(true));
    } else if (!freshMissing && currentMissing) {
      currentMissing.remove();
    }
  }
  // Update tab badge counts
  const freshTabs = doc.querySelectorAll(".tab[data-tab] .tab-count");
  freshTabs.forEach(freshCount => {
    const tab = freshCount.closest("[data-tab]");
    if (tab) {
      const currentTab = document.querySelector(`.tab[data-tab="${tab.dataset.tab}"] .tab-count`);
      if (currentTab) currentTab.textContent = freshCount.textContent;
    }
  });
  // Update wizard step status subtitles
  ["mail", "fetch", "folder", "triage", "rename", "export"].forEach(step => {
    const freshStatus = doc.getElementById(`wizard-status-${step}`);
    const currentStatus = document.getElementById(`wizard-status-${step}`);
    if (freshStatus && currentStatus) currentStatus.textContent = freshStatus.textContent;
  });
  // Re-bind dismiss buttons on fresh fetch panel
  document.querySelectorAll(".dismiss-provider-btn").forEach(btn => {
    if (btn._dismissBound) return;
    btn._dismissBound = true;
    btn.addEventListener("click", dismissProviderHandler);
  });
  window.scrollTo(0, scrollY);
}

// === Month kanban: collapse & bulk actions ===
(function() {
  function parseIdList(raw) {
    return (raw || "").split(",").filter(Boolean).map(Number);
  }

  async function bulkAccountingType(ids, accountingType) {
    if (!ids.length || !accountingType) return;
    await fetch("/documents/bulk-accounting-type", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ids, accounting_type: accountingType}),
    });
    await refreshDocumentsPanel();
  }

  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".collapse-month-btn");
    if (!btn) return;
    const section = btn.closest(".doc-kanban-section");
    const board = section.querySelector(".kanban-board");
    const collapsed = board.hidden;
    board.hidden = !collapsed;
    btn.textContent = collapsed ? "▼" : "▶";
  });

  // Bulk status change
  async function bulkStatus(ids, status) {
    if (!ids.length) return;
    await fetch("/documents/bulk-status", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ids, status}),
    });
    await refreshDocumentsPanel();
  }

  // Bulk dismiss (permanent)
  async function bulkDismiss(ids) {
    if (!ids.length) return;
    await fetch("/documents/bulk-delete", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ids}),
    });
    await refreshDocumentsPanel();
  }

  function updateKanbanCounts() {
    // Update section counts after DOM removal
    document.querySelectorAll(".doc-kanban-section").forEach(section => {
      const cards = section.querySelectorAll("article");
      const countEl = section.querySelector(".count-label");
      if (countEl) countEl.textContent = cards.length;
      const emptyNote = section.querySelector(".kanban-empty");
      if (cards.length === 0 && !emptyNote) {
        const empty = document.createElement("div");
        empty.className = "kanban-empty";
        empty.textContent = "—";
        const board = section.querySelector(".kanban-board");
        if (board) board.appendChild(empty);
      }
    });
  }

  document.addEventListener("click", (e) => {
    const inclBtn = e.target.closest(".bulk-include-month");
    if (inclBtn) { bulkStatus(parseIdList(inclBtn.dataset.ids), "doc_included"); return; }

    const skipBtn = e.target.closest(".bulk-skip-month");
    if (skipBtn) { bulkStatus(parseIdList(skipBtn.dataset.ids), "review_ignored"); return; }

    const dismissBtn = e.target.closest(".bulk-dismiss-month");
    if (dismissBtn) {
      if (!confirm("Permanently dismiss these skipped documents? They won't reappear.")) return;
      bulkDismiss(parseIdList(dismissBtn.dataset.ids));
      return;
    }

    const accountingBtn = e.target.closest(".bulk-accounting-type");
    if (accountingBtn) {
      const ids = parseIdList(accountingBtn.dataset.ids);
      const accountingType = accountingBtn.dataset.accountingType;
      if (!ids.length || !accountingType) return;
      const originalText = accountingBtn.textContent;
      accountingBtn.disabled = true;
      accountingBtn.textContent = "⏳ Updating…";
      bulkAccountingType(ids, accountingType)
        .catch(() => {
          accountingBtn.disabled = false;
          accountingBtn.textContent = "❌ Error";
          setTimeout(() => { accountingBtn.textContent = originalText; }, 1200);
        });
    }
  });

  // Re-rename button with progress
  document.addEventListener("click", async (e) => {
    const reRenameBtn = e.target.closest("#re-rename-btn");
    if (!reRenameBtn) return;
    reRenameBtn.disabled = true;
    // Insert progress bar after the button
    const bar = document.createElement("div");
    bar.className = "re-rename-progress";
    bar.innerHTML = '<div class="re-rename-progress-track"><div class="re-rename-progress-fill"></div></div><span class="re-rename-progress-label">Starting…</span>';
    reRenameBtn.parentElement.appendChild(bar);
    const fill = bar.querySelector(".re-rename-progress-fill");
    const label = bar.querySelector(".re-rename-progress-label");

    try {
      const resp = await fetch("/documents/re-rename", {method: "POST"});
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        buf += decoder.decode(value, {stream: true});
        const lines = buf.split("\n\n");
        buf = lines.pop();
        for (const line of lines) {
          const m = line.match(/^data: (.+)$/m);
          if (!m) continue;
          const evt = JSON.parse(m[1]);
          if (evt.type === "start") {
            label.textContent = `0 / ${evt.total}`;
          } else if (evt.type === "progress") {
            const pct = Math.round((evt.current / evt.total) * 100);
            fill.style.width = pct + "%";
            label.textContent = `${evt.current} / ${evt.total} — ${evt.filename}`;
          } else if (evt.type === "done") {
            fill.style.width = "100%";
            label.textContent = `✓ ${evt.updated} documents updated`;
            setTimeout(() => location.reload(), 1000);
          }
        }
      }
    } catch (err) {
      label.textContent = "❌ Error";
      reRenameBtn.disabled = false;
    }
  });
})();

// === Triage tabs and bulk actions ===
(function() {
  // Tab switching
  document.addEventListener("click", (e) => {
    const tab = e.target.closest(".triage-tab");
    if (!tab) return;
    const section = tab.closest(".doc-triage-section");
    if (!section) return;
      section.querySelectorAll(".triage-tab").forEach(t => t.classList.remove("active"));
      section.querySelectorAll(".triage-tab-panel").forEach(p => p.classList.remove("active"));
      tab.classList.add("active");
      const panel = section.querySelector(`[data-triage-panel="${tab.dataset.triageTab}"]`);
      if (panel) panel.classList.add("active");
  });

  // Bulk accept suggested
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".bulk-accept-suggested");
    if (!btn) return;
    const ids = (btn.dataset.ids || "").split(",").filter(Boolean).map(Number);
    if (!ids.length) return;
    btn.disabled = true;
    btn.textContent = "⏳ Processing…";
    try {
      const resp = await fetch("/documents/bulk-accept-suggested", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ids}),
      });
      const data = await resp.json();
      btn.textContent = `✓ ${data.count} accepted`;
      setTimeout(() => refreshDocumentsPanel(), 400);
    } catch (err) {
      btn.textContent = "❌ Error";
      btn.disabled = false;
    }
  });

  // Bulk skip triage
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".bulk-skip-triage");
    if (!btn) return;
    const ids = (btn.dataset.ids || "").split(",").filter(Boolean).map(Number);
    if (!ids.length) return;
    btn.disabled = true;
    btn.textContent = "⏳ Skipping…";
    try {
      await fetch("/documents/bulk-status", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ids, status: "review_ignored"}),
      });
      btn.textContent = `✓ ${ids.length} skipped`;
      setTimeout(() => refreshDocumentsPanel(), 400);
    } catch (err) {
      btn.textContent = "❌ Error";
      btn.disabled = false;
    }
  });
})();

// === Accounting type controls ===
(function() {
  function getAccountingTypeMeta(accountingType) {
    if (accountingType === "purchase") {
      return { label: "📥 Achat", className: "accounting-type-purchase" };
    }
    if (accountingType === "sale") {
      return { label: "📤 Vente", className: "accounting-type-sale" };
    }
    return { label: "❓", className: "accounting-type-unknown" };
  }

  function updateAccountingTypeInline(select, accountingType) {
    const wrapper = select.closest(".accounting-type-inline");
    const badge = wrapper?.querySelector(".accounting-type-badge");
    if (!badge) return;
    const meta = getAccountingTypeMeta(accountingType);
    badge.textContent = meta.label;
    badge.className = `badge accounting-type-badge ${meta.className}`;
    select.dataset.accountingType = accountingType || "";
  }

  document.addEventListener("change", async (e) => {
    const select = e.target.closest(".accounting-type-select");
    if (!select) return;
    const previousValue = select.dataset.accountingType || "";
    const nextValue = select.value;
    if (!nextValue || nextValue === previousValue) return;
    select.disabled = true;

    try {
      const formData = new FormData();
      formData.append("accounting_type", nextValue);
      const resp = await fetch(`/documents/${select.dataset.documentId}/accounting-type`, {
        method: "POST",
        body: formData,
      });
      if (!resp.ok) throw new Error(`Server error: ${resp.status}`);
      const data = await resp.json().catch(() => ({}));
      updateAccountingTypeInline(select, data.accounting_type || nextValue);
      await refreshDocumentsPanel();
    } catch (err) {
      select.value = previousValue;
      updateAccountingTypeInline(select, previousValue);
      alert(`Failed to update accounting type: ${err.message}`);
    } finally {
      select.disabled = false;
    }
  });
})();

// === Inline form interception (preserve scroll) ===
(function() {
  document.addEventListener("submit", async (e) => {
    const form = e.target;
    // Intercept inline status forms, rename forms, and the rename modal
    const isInline = form.matches(".inline-form") || form.matches(".rename-form");
    const isRenameModal = form.id === "rename-modal-form";
    if (!isInline && !isRenameModal) return;
    e.preventDefault();

    const action = form.action;
    const submitter = e.submitter;
    const formData = new FormData(form);
    // Include the submit button's name/value (not auto-included by FormData)
    if (submitter && submitter.name) {
      formData.set(submitter.name, submitter.value);
    }
    const card = isRenameModal
      ? document.querySelector(`[data-doc-id="${action.match(/documents\/(\d+)/)?.[1]}"]`)?.closest("article")
      : form.closest("article");

    try {
      await fetch(action, { method: "POST", body: formData, redirect: "manual" });
      if (isRenameModal) {
        document.getElementById("rename-modal").hidden = true;
      }
      if (card) {
        card.style.transition = "opacity 0.2s, transform 0.2s";
        card.style.opacity = "0";
        card.style.transform = "scale(0.95)";
      }
      // After fade, refresh the documents panel in-place
      setTimeout(() => refreshDocumentsPanel(), 250);
    } catch (err) {
      form.submit();
    }
  });

  document.querySelectorAll(".dismiss-provider-btn").forEach(btn => {
    btn.addEventListener("click", dismissProviderHandler);
  });
})();
