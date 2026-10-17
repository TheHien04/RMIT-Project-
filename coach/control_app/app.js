const voiceButton = document.querySelector("#voice-button");
const voiceButtonLabel = document.querySelector("#voice-button-label");
const voiceButtonHint = document.querySelector("#voice-button-hint");
const browserButton = document.querySelector("#browser-button");
const quitButton = document.querySelector("#quit-button");
const quitDialog = document.querySelector("#quit-dialog");
const quitCancel = document.querySelector("#quit-cancel");
const quitConfirm = document.querySelector("#quit-confirm");
const closedView = document.querySelector("#closed-view");
const closeTabButton = document.querySelector("#close-tab-button");
const closeTabHint = document.querySelector("#close-tab-hint");
const browserStatus = document.querySelector("#browser-status");
const voiceStatus = document.querySelector("#voice-status");
const browserReadiness = document.querySelector("#browser-readiness");
const voiceReadiness = document.querySelector("#voice-readiness");
const controlPanel = document.querySelector("#control-panel");
const controlTitle = document.querySelector("#control-title");
const controlMessage = document.querySelector("#control-message");
const sessionDuration = document.querySelector("#session-duration");
const statePill = document.querySelector(".state-pill");
const stateLabel = document.querySelector("#state-label");
const liveStatus = document.querySelector("#live-status");
const errorBox = document.querySelector("#error-box");

let token = "";
let current = null;
let busy = false;
let lastAnnouncement = "";

const stateNames = {
  stopped: "Đang nghỉ",
  starting: "Đang khởi động",
  listening: "Đang nghe",
  stopping: "Đang dừng",
  completed: "Đã hoàn thành",
  error: "Cần kiểm tra",
};

const stateTitles = {
  stopped: "Sẵn sàng khi bạn cần",
  starting: "Mình đang chuẩn bị…",
  listening: "Mình đang nghe",
  stopping: "Mình đang dừng…",
  completed: "Bạn đã hoàn thành phiên học",
  error: "Có một việc cần kiểm tra",
};

async function getStatus() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error("Không đọc được trạng thái ứng dụng.");
    const data = await response.json();
    token = data.token;
    const errorResolved = current && (
      (!current.browser?.tab_ready && data.browser?.tab_ready)
      || (current.state === "error" && data.state !== "error")
    );
    if (errorResolved) clearError();
    render(data);
  } catch (error) {
    showError(error.message, false);
  }
}

async function post(path) {
  if (busy) return false;
  busy = true;
  voiceButton.disabled = true;
  browserButton.disabled = true;
  clearError();
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "X-Coach-Token": token },
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Thao tác chưa hoàn tất.");
    render(data);
    return true;
  } catch (error) {
    showError(error.message);
    return false;
  } finally {
    busy = false;
    voiceButton.disabled = false;
    browserButton.disabled = false;
  }
}

function render(data) {
  current = data;
  const state = data.state || "stopped";
  const active = ["starting", "listening", "stopping"].includes(state);
  const browserReady = Boolean(data.browser?.tab_ready);
  const voiceReady = Boolean(data.ready);
  const displayMessage = state === "stopped" && data.message === "Voice Coach đang tắt."
    ? "Mình đang nghỉ. Khi bạn muốn bắt đầu, cứ gọi mình."
    : data.message || "Coach đang nghỉ.";
  const browserMessage = browserReady
    ? "Supabase đã sẵn sàng."
    : data.browser?.cdp_ready
      ? "Mình chưa thấy đúng tab Supabase."
      : "Mình chưa thấy Chrome học tập. Hãy mở Supabase.";

  controlPanel.dataset.state = state;
  statePill.dataset.state = state;
  stateLabel.textContent = stateNames[state] || "Không xác định";
  controlTitle.textContent = stateTitles[state] || "Trạng thái Voice Coach";
  controlMessage.textContent = displayMessage;
  renderDuration(data.started_at, active);
  voiceStatus.textContent = state === "listening"
    ? "Đang sử dụng micro"
    : state === "starting"
      ? "Đang làm nóng model"
      : state === "stopping"
        ? "Đang giải phóng micro"
        : state === "error"
          ? "Chưa sẵn sàng"
          : "Sẽ kiểm tra khi bắt đầu";
  browserStatus.textContent = browserMessage;
  browserReadiness.dataset.status = browserReady ? "ready" : "waiting";
  voiceReadiness.dataset.status = voiceReady
    ? "ready"
    : ["starting", "stopping"].includes(state)
      ? "checking"
      : "waiting";
  browserButton.hidden = browserReady;

  voiceButton.setAttribute("aria-pressed", String(active));
  if (active) {
    voiceButtonLabel.textContent = state === "stopping" ? "Đang dừng…" : "Dừng hướng dẫn";
    voiceButtonHint.textContent = "Dừng nghe và giữ tiến độ hiện tại";
    voiceButton.disabled = state === "stopping" || busy;
  } else {
    voiceButtonLabel.textContent = "Bắt đầu hướng dẫn";
    voiceButtonHint.textContent = browserReady
      ? "Coach sẽ bắt đầu nghe micro"
      : "Hãy mở đúng tab Supabase trước";
    voiceButton.disabled = busy;
  }

  if (displayMessage && displayMessage !== lastAnnouncement) {
    liveStatus.textContent = displayMessage;
    lastAnnouncement = displayMessage;
  }
}

function renderDuration(startedAt, active) {
  if (!active || !startedAt) {
    sessionDuration.hidden = true;
    sessionDuration.textContent = "Phiên 00:00";
    return;
  }

  const started = new Date(startedAt);
  if (Number.isNaN(started.getTime())) {
    sessionDuration.hidden = true;
    return;
  }

  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - started.getTime()) / 1000));
  const minutes = String(Math.floor(elapsedSeconds / 60)).padStart(2, "0");
  const seconds = String(elapsedSeconds % 60).padStart(2, "0");
  sessionDuration.textContent = `Phiên ${minutes}:${seconds}`;
  sessionDuration.hidden = false;
}

function showError(message, moveFocus = true) {
  errorBox.textContent = message;
  errorBox.hidden = false;
  if (moveFocus) errorBox.focus();
  liveStatus.textContent = `Có lỗi: ${message}`;
}

function clearError() {
  errorBox.hidden = true;
  errorBox.textContent = "";
}

voiceButton.addEventListener("click", () => {
  const active = current && ["starting", "listening", "stopping"].includes(current.state);
  post(active ? "/api/voice/stop" : "/api/voice/start");
});

browserButton.addEventListener("click", async () => {
  await post("/api/browser/open");
  liveStatus.textContent = "Chrome đang mở. Hãy đăng nhập và mở project Supabase cần học.";
});

quitButton.addEventListener("click", async () => {
  quitDialog.showModal();
});

quitCancel.addEventListener("click", () => quitDialog.close());

quitConfirm.addEventListener("click", async () => {
  quitConfirm.disabled = true;
  const closed = await post("/api/app/quit");
  if (!closed) {
    quitConfirm.disabled = false;
    quitDialog.close();
    return;
  }
  quitDialog.close();
  document.querySelector(".site-header").hidden = true;
  document.querySelector("#main").hidden = true;
  document.querySelector("footer").hidden = true;
  closedView.hidden = false;
  closedView.focus();
  clearInterval(statusTimer);
});

closeTabButton.addEventListener("click", () => {
  window.close();
  setTimeout(() => {
    closeTabHint.textContent = "Trình duyệt không cho ứng dụng tự đóng tab. Hãy nhấn Command và W.";
    closeTabHint.setAttribute("role", "status");
  }, 150);
});

getStatus();
const statusTimer = setInterval(getStatus, 1200);
