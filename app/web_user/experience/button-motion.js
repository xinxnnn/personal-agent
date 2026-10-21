'use strict';
(() => {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  function ripple(button, x, y) {
    if (button.disabled || reducedMotion.matches) return;
    button.querySelector('.button-ripple-layer')?.remove();
    const bounds = button.getBoundingClientRect();
    const size = Math.hypot(bounds.width, bounds.height) * 2;
    const layer = document.createElement('span');
    layer.className = 'button-ripple-layer';
    layer.setAttribute('aria-hidden', 'true');
    const circle = document.createElement('span');
    circle.className = 'button-ripple';
    Object.assign(circle.style, {
      width: `${size}px`, height: `${size}px`,
      left: `${x - size / 2}px`, top: `${y - size / 2}px`
    });
    layer.append(circle);
    button.append(layer);
    setTimeout(() => layer.remove(), 550);
  }
  document.addEventListener('pointerdown', event => {
    if (!event.isPrimary || event.button !== 0) return;
    const button = event.target.closest('button');
    if (!button) return;
    const bounds = button.getBoundingClientRect();
    ripple(button, event.clientX - bounds.left, event.clientY - bounds.top);
  }, { passive: true });
  document.addEventListener('click', event => {
    // Keyboard and assistive-technology activations originate at the center.
    if (event.detail !== 0) return;
    const button = event.target.closest('button');
    if (!button) return;
    ripple(button, button.clientWidth / 2, button.clientHeight / 2);
  });
})();
