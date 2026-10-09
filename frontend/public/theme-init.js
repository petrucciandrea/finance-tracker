// Applies the saved theme before first paint. Doing it from React instead would
// flash the light palette on every load in dark mode.
// External file (not inline) so the Content-Security-Policy can be `script-src 'self'`.
// Keep the storage key in sync with src/context/theme.ts.
;(function () {
  try {
    var pref = localStorage.getItem('finance_tracker_theme')
    var dark = pref === 'dark' ||
      (pref !== 'light' && window.matchMedia('(prefers-color-scheme: dark)').matches)
    if (dark) document.documentElement.classList.add('dark')
  } catch (e) { /* storage blocked: stay on the light default */ }
})()
