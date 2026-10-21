'use strict';
// Suspend decorative animation while the tab is in the background.
(() => {
  const update = () => document.documentElement.classList.toggle('motion-paused', document.hidden);
  document.addEventListener('visibilitychange', update);
  update();
})();
