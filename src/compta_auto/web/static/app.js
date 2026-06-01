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

// === Preview modal ===
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
