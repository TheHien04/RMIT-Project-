const flow = new URLSearchParams(location.search).get("flow") === "button" ? "button" : "div";
const labels = ["Tạo bảng", "Thêm cột", "Lưu bảng"];
const columns = [];

document.getElementById("flow-note").textContent = flow === "button"
  ? "Flow đối chứng: control là button thật."
  : "Flow demo: control là div, không có role, không nằm trong thứ tự Tab.";

const host = document.getElementById("controls");
labels.forEach((label) => {
  const el = flow === "button" ? document.createElement("button") : document.createElement("div");
  el.dataset.coach = label;
  el.textContent = label;
  el.className = "control";
  if (flow !== "button") el.tabIndex = -1;
  el.addEventListener("click", () => onAction(label));
  host.appendChild(el);
});

function onAction(label) {
  if (label === "Tạo bảng") {
    document.body.dataset.panel = "open";
  } else if (label === "Thêm cột") {
    if (document.body.dataset.panel !== "open") return;
    if (!columns.includes("Ca")) columns.push("Ca");
    else if (!columns.includes("Người")) columns.push("Người");
    document.body.dataset.columns = columns.join(",");
  } else if (label === "Lưu bảng") {
    if (columns.includes("Ca") && columns.includes("Người")) {
      document.body.dataset.saved = "true";
    }
  }
  render();
}

function render() {
  const open = document.body.dataset.panel === "open";
  const saved = document.body.dataset.saved === "true";
  document.getElementById("empty").hidden = open;
  const wrap = document.getElementById("table-wrap");
  wrap.hidden = !open;
  wrap.replaceChildren();
  if (open) {
    const table = document.createElement("table");
    const head = document.createElement("tr");
    if (columns.length === 0) {
      const cell = document.createElement("th");
      cell.textContent = "Bảng trống";
      head.appendChild(cell);
    }
    columns.forEach((name) => {
      const cell = document.createElement("th");
      cell.textContent = name;
      head.appendChild(cell);
    });
    table.appendChild(head);
    wrap.appendChild(table);
  }
  document.getElementById("saved").hidden = !saved;
}

render();
