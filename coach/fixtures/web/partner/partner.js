const state = document.querySelector("#auth-state");
const login = document.querySelector("#manual-login");
const dashboard = document.querySelector("#dashboard");
const project = document.querySelector("#create-project");
const result = document.querySelector("#result");

login.addEventListener("click", () => {
  state.textContent = "Đã đăng nhập thủ công";
  login.hidden = true;
  dashboard.hidden = false;
});

project.addEventListener("click", () => {
  history.pushState({}, "", "?page=dashboard");
  result.textContent = "Dự án đã được tạo";
});
