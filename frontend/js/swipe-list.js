/** @typedef {object} SwipePointerState
 * @property {number | null} pointerId
 * @property {number} startX
 * @property {number} startY
 * @property {number} currentX
 * @property {number} offset
 * @property {boolean} swiping
 * @property {boolean} locked
 */

/** @typedef {object} SwipeListOptions
 * @property {number} [reveal]
 * @property {number} [slop]
 */

const DEFAULT_REVEAL = 192;
const DEFAULT_SLOP = 8;

/** @type {WeakMap<HTMLElement, SwipePointerState>} */
const swipeStates = new WeakMap();

/** @type {WeakSet<HTMLElement>} */
const boundContents = new WeakSet();

/**
 * @param {HTMLElement} content
 * @returns {number}
 */
function getRevealWidth(content) {
  const row = content.closest('[data-swipe-row]');
  if (!(row instanceof HTMLElement)) {
    return DEFAULT_REVEAL;
  }
  const customReveal = Number.parseInt(row.dataset.swipeReveal || '', 10);
  if (Number.isFinite(customReveal) && customReveal > 0) {
    return customReveal;
  }
  const actions = row.querySelector('[data-swipe-actions]');
  if (actions instanceof HTMLElement && actions.offsetWidth > 0) {
    return actions.offsetWidth;
  }
  return DEFAULT_REVEAL;
}

/**
 * @param {HTMLElement} content
 * @param {number} x
 * @param {boolean} animated
 */
function setTransform(content, x, animated) {
  content.style.transform = `translate3d(${x}px, 0, 0)`;
  content.style.transition = animated
    ? 'transform .25s cubic-bezier(.3,.8,.4,1)'
    : 'none';
}

/**
 * @param {HTMLElement} content
 */
function resetContent(content) {
  const state = swipeStates.get(content);
  if (!state) {
    return;
  }
  state.offset = 0;
  state.swiping = false;
  state.pointerId = null;
  content.classList.remove('swiping');
  setTransform(content, 0, true);
}

/**
 * @param {HTMLElement | null} except
 */
function resetOtherRows(except) {
  document.querySelectorAll('[data-swipe-content]').forEach((node) => {
    if (!(node instanceof HTMLElement) || node === except) {
      return;
    }
    const state = swipeStates.get(node);
    if (state && state.offset !== 0) {
      resetContent(node);
    }
  });
}

/**
 * @param {HTMLElement} content
 * @param {SwipeListOptions} [options]
 */
export function bindSwipeContent(content, options = {}) {
  if (boundContents.has(content)) {
    return;
  }
  boundContents.add(content);

  const slop = options.slop ?? DEFAULT_SLOP;

  /** @type {SwipePointerState} */
  const state = {
    pointerId: null,
    startX: 0,
    startY: 0,
    currentX: 0,
    offset: 0,
    swiping: false,
    locked: false,
  };
  swipeStates.set(content, state);

  content.addEventListener('pointerdown', (event) => {
    if (event.pointerType !== 'touch' && event.pointerType !== 'pen') {
      if (event.button !== 0) {
        return;
      }
    }
    resetOtherRows(content);
    state.pointerId = event.pointerId;
    state.startX = event.clientX;
    state.startY = event.clientY;
    state.currentX = event.clientX;
    state.locked = false;
    state.swiping = false;
  });

  content.addEventListener(
    'pointermove',
    (event) => {
      if (state.pointerId !== event.pointerId) {
        return;
      }
      const dx = event.clientX - state.startX;
      const dy = event.clientY - state.startY;
      if (!state.locked) {
        if (Math.abs(dx) < slop && Math.abs(dy) < slop) {
          return;
        }
        if (Math.abs(dy) > Math.abs(dx)) {
          state.pointerId = null;
          return;
        }
        state.locked = true;
        state.swiping = true;
        content.classList.add('swiping');
        try {
          content.setPointerCapture(event.pointerId);
        } catch {
          /* ignore */
        }
      }
      const reveal = getRevealWidth(content);
      let next = state.offset + dx;
      if (next > 0) {
        next = 0;
      }
      if (next < -reveal) {
        next = -reveal;
      }
      state.currentX = next;
      setTransform(content, next, false);
      event.preventDefault();
    },
    { passive: false },
  );

  /**
   * @param {PointerEvent} event
   */
  function release(event) {
    if (state.pointerId !== event.pointerId) {
      return;
    }
    try {
      content.releasePointerCapture(event.pointerId);
    } catch {
      /* ignore */
    }
    state.pointerId = null;
    if (!state.swiping) {
      return;
    }
    content.classList.remove('swiping');
    state.swiping = false;
    const reveal = getRevealWidth(content);
    const snap = state.currentX < -reveal / 2 ? -reveal : 0;
    state.offset = snap;
    setTransform(content, snap, true);
  }

  content.addEventListener('pointerup', release);
  content.addEventListener('pointercancel', release);

  const row = content.closest('[data-swipe-row]');
  if (row) {
    row.querySelectorAll('[data-swipe-actions] a, [data-swipe-actions] button').forEach(
      (action) => {
        action.addEventListener('click', () => {
          resetContent(content);
        });
      },
    );
  }
}

/**
 * @param {ParentNode} [root]
 * @param {SwipeListOptions} [options]
 */
export function initSwipeList(root = document, options = {}) {
  root.querySelectorAll('[data-swipe-content]').forEach((node) => {
    if (node instanceof HTMLElement) {
      bindSwipeContent(node, options);
    }
  });
}

export function initSwipeListGlobal() {
  const run = () => initSwipeList(document);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run, { once: true });
  } else {
    run();
  }

  document.addEventListener('htmx:afterSwap', (event) => {
    const target = event.detail?.target;
    if (target instanceof HTMLElement) {
      initSwipeList(target);
    }
  });
}

initSwipeListGlobal();
