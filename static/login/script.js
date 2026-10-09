const password = document.getElementById('password');
const toggle = document.querySelector('.password-toggle');
toggle.addEventListener('click', () => {
  const visible = password.type === 'password';
  password.type = visible ? 'text' : 'password';
  toggle.setAttribute('aria-pressed', String(visible));
  toggle.setAttribute('aria-label', visible ? '隐藏密码' : '显示密码');
});
document.getElementById('login-form').addEventListener('submit', () => {
  const button = document.querySelector('.submit-button');
  button.disabled = true;
  button.textContent = '正在登录…';
});
window.addEventListener('pageshow', () => {
  const button = document.querySelector('.submit-button');
  button.disabled = false;
  button.innerHTML = '登 录 <span aria-hidden="true">→</span>';
});
