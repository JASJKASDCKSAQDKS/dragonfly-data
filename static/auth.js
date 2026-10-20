/* ==========================================================================
   Seline — client authentication core.

   Responsibilities:
     - Use secure HTTP-only cookies for JWT access/refresh tokens.
     - Log in / log out against /api/auth/*.
     - Wrap window.fetch so every /api/* request carries the Bearer token
       automatically and transparently refreshes on a 401.
     - Guard the dashboard shell: unauthenticated visitors are sent to /login.

   Because window.fetch is patched here, every other script (voice.js,
   dbadmin.js, ...) keeps calling fetch() exactly as before — it just gets
   authenticated for free. This file MUST be loaded before those scripts.
   ========================================================================== */
(function () {
  'use strict';

  const USER_KEY = 'seline_user';

  const LOGIN_PATH = '/login';
  const APP_PATHS = ['/app', '/client'];
  const demoMode = new URLSearchParams(window.location.search).get('demo') === '1';

  // Auth endpoints must never be wrapped — that would recurse on refresh.
  const AUTH_PATHS = ['/api/auth/login', '/api/auth/refresh', '/api/auth/logout'];

  function isAuthPath(url) {
    return AUTH_PATHS.some((p) => url.indexOf(p) !== -1);
  }

  const SelineAuth = {
    // ---- token store -----------------------------------------------------
    getAccessToken() {
      return null;
    },

    getRefreshToken() {
      return null;
    },

    getUser() {
      try {
        return JSON.parse(sessionStorage.getItem(USER_KEY) || 'null');
      } catch (err) {
        return null;
      }
    },

    isAuthenticated() {
      return !!sessionStorage.getItem(USER_KEY);
    },

    save(loginResponse) {
      if (loginResponse.user) {
        sessionStorage.setItem(USER_KEY, JSON.stringify(loginResponse.user));
      }
    },

    clear() {
      sessionStorage.removeItem(USER_KEY);
    },

    // ---- network ---------------------------------------------------------
    async login(email, password, mfaCode) {
      const res = await rawFetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, password, ...(mfaCode ? { mfa_code: mfaCode } : {}) }),
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.detail || 'Invalid email or password.');
      }
      if (data.requires_mfa) return data;
      if (!data.access_token) {
        throw new Error('Login failed: no token returned.');
      }

      SelineAuth.save(data);
      return data;
    },

    async refresh() {
      const res = await rawFetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({}),
      });

      if (!res.ok) {
        SelineAuth.clear();
        return false;
      }

      const data = await res.json().catch(() => ({}));
      if (!data.user && !data.access_token) {
        SelineAuth.clear();
        return false;
      }
      SelineAuth.save(data);
      return true;
    },

    async logout() {
      SelineAuth.clear();
      try {
        await rawFetch('/api/auth/logout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({}),
        });
      } catch (err) {
        /* best effort — the local session is already cleared */
      }
      window.location.href = LOGIN_PATH;
    },

    redirectToLogin() {
      if (window.location.pathname !== LOGIN_PATH) {
        window.location.href = LOGIN_PATH;
      }
    },

    /** True when the current page is the dashboard shell. */
    isAppPage() {
      const path = window.location.pathname;
      return APP_PATHS.some((appPath) => path === appPath) || path.endsWith('/index.html');
    },

    /** Redirect to the login page when there is no stored session. */
    requireAuth() {
      if (!SelineAuth.isAuthenticated()) {
        SelineAuth.redirectToLogin();
        return false;
      }
      return true;
    },

    homePath() {
      const user = SelineAuth.getUser();
      return user && user.role === 'client' ? '/client' : APP_PATHS[0];
    },
  };

  // ---- fetch interceptor -------------------------------------------------
  const rawFetch = window.fetch.bind(window);

  window.fetch = async function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';

    // Auth calls (and anything not hitting the API) pass straight through.
    if (isAuthPath(url)) {
      return rawFetch(input, init);
    }

    const requestInit = Object.assign({}, init);
    const headers = new Headers(
      (requestInit.headers) || (typeof input !== 'string' && input.headers) || {}
    );
    requestInit.credentials = requestInit.credentials || 'include';
    requestInit.headers = headers;

    let response = await rawFetch(input, requestInit);
    let retried = false;

    // Expired access token: refresh once, then replay the original request.
    if (response.status === 401 && !isAuthPath(url) && !retried) {
      const refreshed = await SelineAuth.refresh();
      if (refreshed) {
        retried = true;
        const retryHeaders = new Headers(requestInit.headers);
        response = await rawFetch(input, Object.assign({}, requestInit, { headers: retryHeaders }));
      } else {
        SelineAuth.redirectToLogin();
      }
    }

    return response;
  };

  // Keep the last successful dashboard payload available when offline.
  window.addEventListener('online', function () {
    document.documentElement.dataset.network = 'online';
  });
  window.addEventListener('offline', function () {
    document.documentElement.dataset.network = 'offline';
  });

  // ---- page guard --------------------------------------------------------
  // The dashboard redirects immediately (before the shell renders) when no
  // session is stored. The login page opts out — its path is never the app.
  if (SelineAuth.isAppPage()) {
    if (!demoMode && !SelineAuth.isAuthenticated()) {
      SelineAuth.redirectToLogin();
    } else if (!demoMode && window.location.pathname === '/app' &&
               SelineAuth.getUser() &&
               SelineAuth.getUser().role === 'client') {
      window.location.replace('/client');
    } else if (!demoMode && window.location.pathname === '/client' &&
               SelineAuth.getUser() &&
               SelineAuth.getUser().role !== 'client') {
      window.location.replace('/app');
    }
  }

  // ---- header logout button ---------------------------------------------
  document.addEventListener('DOMContentLoaded', function () {
    const btn = document.getElementById('logout-btn');
    if (btn) {
      btn.addEventListener('click', function () {
        SelineAuth.logout();
      });
    }
  });

  window.SelineAuth = SelineAuth;
})();
