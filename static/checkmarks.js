/* Independent, occasional glints. No animation is needed to read a mark. */
(() => {
  'use strict';
  const selector = '.checkmark.shiny_purple:not(.unearned):not(.empty-box)';
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  const active = new Map();
  function stop(mark) {
    clearTimeout(active.get(mark));
    active.delete(mark);
    mark.classList.remove('shimmer');
  }
  function schedule(mark) {
    // Exponential waiting times: on average one glint per minute per visible mark.
    const delay = -Math.log(1 - Math.random()) * 60000;
    active.set(mark, setTimeout(() => {
      if (!mark.isConnected || document.hidden || motion.matches) { stop(mark); return; }
      mark.classList.add('shimmer');
      active.set(mark, setTimeout(() => {
        mark.classList.remove('shimmer');
        schedule(mark);
      }, 900));
    }, delay));
  }
  function refresh() {
    const visible = new Set(document.hidden || motion.matches ? [] :
      [...document.querySelectorAll(selector)].filter(mark => {
        const rect = mark.getBoundingClientRect();
        return rect.width && rect.height && rect.bottom > 0 && rect.top < innerHeight &&
          rect.right > 0 && rect.left < innerWidth;
      }));
    for (const mark of active.keys()) if (!visible.has(mark)) stop(mark);
    for (const mark of visible) if (!active.has(mark)) schedule(mark);
  }
  let queued = false;
  function queueRefresh() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; refresh(); });
  }
  new MutationObserver(queueRefresh).observe(document.documentElement, {childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'hidden', 'open']});
  document.addEventListener('visibilitychange', refresh);
  document.addEventListener('scroll', queueRefresh, {capture: true, passive: true});
  window.addEventListener('resize', queueRefresh);
  motion.addEventListener('change', refresh);
  queueRefresh();
})();
