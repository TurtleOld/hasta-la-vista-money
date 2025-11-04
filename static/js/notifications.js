class ToastNotification {
    constructor() {
        this.container = this.createContainer();
        this.toasts = [];
    }

    createContainer() {
        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            container.className = 'toast-container';
            document.body.appendChild(container);
        }
        return container;
    }

    show(message, type = 'info', duration = 4000) {
        const toast = this.createToast(message, type);
        this.container.appendChild(toast);
        this.toasts.push(toast);

        setTimeout(() => {
            toast.classList.add('show');
        }, 10);

        if (duration > 0) {
            setTimeout(() => {
                this.hide(toast);
            }, duration);
        }

        return toast;
    }

    createToast(message, type) {
        const toast = document.createElement('div');
        toast.className = `toast-notification toast-${type}`;

        const iconMap = {
            'success': 'bi-check-circle-fill',
            'danger': 'bi-exclamation-circle-fill',
            'info': 'bi-info-circle-fill',
            'warning': 'bi-exclamation-triangle-fill'
        };

        const icon = iconMap[type] || iconMap['info'];

        toast.innerHTML = `
            <div class="toast-content">
                <i class="bi ${icon} toast-icon"></i>
                <span class="toast-message">${message}</span>
                <button class="toast-close" aria-label="Закрыть">
                    <i class="bi bi-x"></i>
                </button>
            </div>
        `;

        const closeBtn = toast.querySelector('.toast-close');
        closeBtn.addEventListener('click', () => this.hide(toast));

        return toast;
    }

    hide(toast) {
        toast.classList.remove('show');
        toast.classList.add('hide');

        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
            const index = this.toasts.indexOf(toast);
            if (index > -1) {
                this.toasts.splice(index, 1);
            }
        }, 300);
    }

    success(message, duration) {
        return this.show(message, 'success', duration);
    }

    error(message, duration) {
        return this.show(message, 'danger', duration);
    }

    info(message, duration) {
        return this.show(message, 'info', duration);
    }

    warning(message, duration) {
        return this.show(message, 'warning', duration);
    }

    clear() {
        this.toasts.forEach(toast => this.hide(toast));
    }
}

if (typeof window !== 'undefined') {
    window.toast = new ToastNotification();
}
