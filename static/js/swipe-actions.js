class SwipeActions {
    constructor(selector, options = {}) {
        this.selector = selector;
        this.options = {
            threshold: 80,
            deleteCallback: null,
            editCallback: null,
            ...options
        };
        this.activeItem = null;
        this.init();
    }

    init() {
        if (window.matchMedia('(max-width: 767px)').matches) {
            this.attachListeners();
        }

        window.addEventListener('resize', () => {
            if (window.matchMedia('(max-width: 767px)').matches) {
                this.attachListeners();
            } else {
                this.detachListeners();
            }
        });
    }

    attachListeners() {
        document.addEventListener('touchstart', this.handleTouchStart.bind(this), { passive: true });
        document.addEventListener('touchmove', this.handleTouchMove.bind(this), { passive: false });
        document.addEventListener('touchend', this.handleTouchEnd.bind(this));
    }

    detachListeners() {
        document.removeEventListener('touchstart', this.handleTouchStart.bind(this));
        document.removeEventListener('touchmove', this.handleTouchMove.bind(this));
        document.removeEventListener('touchend', this.handleTouchEnd.bind(this));
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
        if (!this.activeItem || !this.isSwiping) {
            if (this.activeItem) {
                this.activeItem.classList.remove('swiping');
            }
            this.activeItem = null;
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
}

if (typeof window !== 'undefined') {
    window.SwipeActions = SwipeActions;
}
