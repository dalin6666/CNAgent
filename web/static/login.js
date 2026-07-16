const passwordInput = document.querySelector("#password");
const passwordToggle = document.querySelector("[data-password-toggle]");
const loginForm = document.querySelector("[data-login-form]");

if (passwordInput && passwordToggle) {
  passwordToggle.addEventListener("click", () => {
    const shouldShow = passwordInput.type === "password";
    passwordInput.type = shouldShow ? "text" : "password";
    const label = shouldShow ? "隐藏密码" : "显示密码";
    passwordToggle.setAttribute("aria-label", label);
    passwordToggle.setAttribute("title", label);
    passwordToggle.querySelector("img").src = shouldShow
      ? passwordToggle.dataset.hideIcon
      : passwordToggle.dataset.showIcon;
    passwordInput.focus();
  });
}

if (loginForm) {
  loginForm.addEventListener("submit", () => {
    const button = loginForm.querySelector("[data-submit-button]");
    const label = loginForm.querySelector("[data-button-label]");
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    label.textContent = "正在登录";
  });
}
