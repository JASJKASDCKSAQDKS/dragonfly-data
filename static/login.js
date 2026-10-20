/* ==========================================================================
   Seline — login page controller.

   Submits credentials to /api/auth/login (via SelineAuth), stores the
   session, then hands off to the dashboard at /app. If a valid session is
   already stored, it skips straight to the dashboard.
   ========================================================================== */
(function () {
  'use strict';

  const form = document.getElementById('login-form');
  const emailInput = document.getElementById('email');
  const passwordInput = document.getElementById('password');
  const button = document.getElementById('login-btn');
  const errorBox = document.getElementById('login-error');
  const mfaField = document.getElementById('mfa-field');
  const mfaInput = document.getElementById('mfa-code');

  // Already signed in? Go straight to the app.
  if (window.SelineAuth && window.SelineAuth.isAuthenticated()) {
    window.location.replace(window.SelineAuth.homePath());
    return;
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.classList.add('show');
    // Re-trigger the shake animation on repeat failures.
    errorBox.style.animation = 'none';
    void errorBox.offsetWidth;
    errorBox.style.animation = '';
  }

  function clearError() {
    errorBox.textContent = '';
    errorBox.classList.remove('show');
  }

  function setLoading(loading) {
    button.disabled = loading;
    button.classList.toggle('loading', loading);
    button.querySelector('.btn-label').textContent = loading ? 'Signing in…' : 'Sign in';
  }

  async function handleSubmit(event) {
    event.preventDefault();
    clearError();

    const email = emailInput.value.trim();
    const password = passwordInput.value;

    if (!email || !password) {
      showError('Enter both your email and password.');
      return;
    }

    setLoading(true);
    try {
      const data = await window.SelineAuth.login(email, password, mfaInput.value.trim());
      if (data.requires_mfa) {
        mfaField.hidden = false;
        showError('Enter the six-digit authenticator code.');
        mfaInput.focus();
        setLoading(false);
        return;
      }
      window.location.replace(data.user && data.user.role === 'client' ? '/client' : '/app');
    } catch (err) {
      showError(err && err.message ? err.message : 'Sign in failed. Try again.');
      passwordInput.value = '';
      passwordInput.focus();
      setLoading(false);
    }
  }

  form.addEventListener('submit', handleSubmit);
  emailInput.focus();
})();
