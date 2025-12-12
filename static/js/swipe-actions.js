class SwipeActions {
    constructor(selector, options = {}) {
        this.selector = selector;
        this.options = {
            threshold: 80,
            deleteCallback: null,
            editCallback: null,
            debounceDelay: 16,
            resizeDebounceDelay: 150,
            ...options
        };
        this.activeItem = null;
        this.isMobile = false;
        this.resizeTimeout = null;
        this.touchMoveTimeout = null;
        this.init();
    }

    debounce(func, delay) {
        let timeoutId;
        return (...args) => {
            clearTimeout(timeoutId);
            timeoutId = setTimeout(() => func.apply(this, args), delay);
        };
    }

    throttle(func, delay) {
        let lastCall = 0;
        return (...args) => {
            const now = Date.now();
            if (now - lastCall >= delay) {
                lastCall = now;
                func.apply(this, args);
            }
        };
    }

    init() {
        this.checkViewport();
        this.handleResize = this.debounce(this.onResize.bind(this), this.options.resizeDebounceDelay);
        window.addEventListener('resize', this.handleResize, { passive: true });
        
        if ('orientationchange' in window) {
            window.addEventListener('orientationchange', this.handleResize, { passive: true });
        }
    }

    checkViewport() {
        const wasMobile = this.isMobile;
        this.isMobile = window.matchMedia('(max-width: 767px)').matches;
        
        if (this.isMobile && !wasMobile) {
            this.attachListeners();
        } else if (!this.isMobile && wasMobile) {
            this.detachListeners();
            if (this.activeItem) {
                this.resetItem(this.activeItem);
                this.activeItem = null;
            }
        }
    }

    onResize() {
        this.checkViewport();
    }

    attachListeners() {
        if (this.listenersAttached) return;
        
        this.boundTouchStart = this.handleTouchStart.bind(this);
        this.boundTouchMove = this.throttle(this.handleTouchMove.bind(this), this.options.debounceDelay);
        this.boundTouchEnd = this.handleTouchEnd.bind(this);
        
        document.addEventListener('touchstart', this.boundTouchStart, { passive: true });
        document.addEventListener('touchmove', this.boundTouchMove, { passive: false });
        document.addEventListener('touchend', this.boundTouchEnd, { passive: true });
        
        this.listenersAttached = true;
    }

    detachListeners() {
        if (!this.listenersAttached) return;
        
        document.removeEventListener('touchstart', this.boundTouchStart);
        document.removeEventListener('touchmove', this.boundTouchMove);
        document.removeEventListener('touchend', this.boundTouchEnd);
        
        this.listenersAttached = false;
    }

    handleTouchStart(e) {
        const item = e.target.closest(this.selector);
        if (!item) return;

        if (this.activeItem && this.activeItem !== item) {
            this.resetItem(this.activeItem);
        }

        this.activeItem = item;
        this.startX = e.touches[0].clientX;
        this.currentX = this.startX;
        this.isSwiping = false;

        item.classList.add('swiping');
    }

    handleTouchMove(e) {
        if (!this.activeItem) return;

        this.currentX = e.touches[0].clientX;
        const diff = this.currentX - this.startX;

        if (Math.abs(diff) > 10) {
            this.isSwiping = true;
            e.preventDefault();

            const maxSwipe = 150;
            const translateX = Math.max(-maxSwipe, Math.min(maxSwipe, diff));

            this.activeItem.style.transform = `translateX(${translateX}px)`;
            this.activeItem.style.transition = 'none';

            if (Math.abs(diff) > this.options.threshold) {
                this.showActions(this.activeItem, diff < 0 ? 'left' : 'right');
            } else {
                this.hideActions(this.activeItem);
            }
        }
    }

    handleTouchEnd() {
        if (this.touchMoveTimeout) {
            clearTimeout(this.touchMoveTimeout);
            this.touchMoveTimeout = null;
        }

        if (!this.activeItem || !this.isSwiping) {
            if (this.activeItem) {
                this.activeItem.classList.remove('swiping');
            }
            this.activeItem = null;
            this.isSwiping = false;
            return;
        }

        const diff = this.currentX - this.startX;
        const absDiff = Math.abs(diff);

        this.activeItem.style.transition = 'transform 0.3s ease';

        if (absDiff < this.options.threshold) {
            this.resetItem(this.activeItem);
        } else {
            if (diff < 0) {
                this.activeItem.style.transform = `translateX(-${this.options.threshold}px)`;
                this.showActions(this.activeItem, 'left');
            } else {
                this.activeItem.style.transform = `translateX(${this.options.threshold}px)`;
                this.showActions(this.activeItem, 'right');
            }
        }

        this.activeItem.classList.remove('swiping');
        this.isSwiping = false;
    }

    showActions(item, direction) {
        let actions = item.querySelector('.swipe-actions');

        if (!actions) {
            actions = document.createElement('div');
            actions.className = 'swipe-actions';

            if (direction === 'left') {
                actions.innerHTML = `
                    <button class="swipe-action swipe-action-delete" data-action="delete">
                        <i class="bi bi-trash"></i>
                    </button>
                `;
                actions.style.right = '0';
            } else {
                actions.innerHTML = `
                    <button class="swipe-action swipe-action-edit" data-action="edit">
                        <i class="bi bi-pencil"></i>
                    </button>
                `;
                actions.style.left = '0';
            }

            item.appendChild(actions);

            actions.addEventListener('click', (e) => {
                e.stopPropagation();
                const action = e.target.closest('[data-action]');
                if (action) {
                    this.handleAction(item, action.dataset.action);
                }
            });
        }

        actions.classList.add('visible');
        actions.setAttribute('data-direction', direction);
    }

    hideActions(item) {
        const actions = item.querySelector('.swipe-actions');
        if (actions) {
            actions.classList.remove('visible');
        }
    }

    resetItem(item) {
        if (!item) return;

        item.style.transform = 'translateX(0)';
        item.style.transition = 'transform 0.3s ease';
        this.hideActions(item);

        setTimeout(() => {
            const actions = item.querySelector('.swipe-actions');
            if (actions) {
                actions.remove();
            }
        }, 300);
    }

    handleAction(item, action) {
        const id = item.dataset.id;

        if (action === 'delete' && this.options.deleteCallback) {
            this.options.deleteCallback(id, item);
        } else if (action === 'edit' && this.options.editCallback) {
            this.options.editCallback(id, item);
        }

        this.resetItem(item);
        this.activeItem = null;
    }

    destroy() {
        this.detachListeners();
        if (this.handleResize) {
            window.removeEventListener('resize', this.handleResize);
            if ('orientationchange' in window) {
                window.removeEventListener('orientationchange', this.handleResize);
            }
        }
        if (this.activeItem) {
            this.resetItem(this.activeItem);
            this.activeItem = null;
        }
        if (this.resizeTimeout) {
            clearTimeout(this.resizeTimeout);
        }
        if (this.touchMoveTimeout) {
            clearTimeout(this.touchMoveTimeout);
        }
    }
}

if (typeof window !== 'undefined') {
    window.SwipeActions = SwipeActions;
}
