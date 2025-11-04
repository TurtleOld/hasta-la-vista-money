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

        const iconMap = new Map([
            ['success', 'bi-check-circle-fill'],
            ['danger', 'bi-exclamation-circle-fill'],
            ['info', 'bi-info-circle-fill'],
            ['warning', 'bi-exclamation-triangle-fill']
        ]);

        const safeType = iconMap.has(type) ? type : 'info';
        const icon = iconMap.get(safeType);

        toast.className = `toast-notification toast-${safeType}`;

        const content = document.createElement('div');
        content.className = 'toast-content';

        const iconElement = document.createElement('i');
        iconElement.className = `bi ${icon} toast-icon`;

        const messageElement = document.createElement('span');
        messageElement.className = 'toast-message';
        messageElement.textContent = message;

        const closeBtn = document.createElement('button');
        closeBtn.className = 'toast-close';
        closeBtn.setAttribute('aria-label', 'Закрыть');

        const closeIcon = document.createElement('i');
        closeIcon.className = 'bi bi-x';
        closeBtn.appendChild(closeIcon);

        content.appendChild(iconElement);
        content.appendChild(messageElement);
        content.appendChild(closeBtn);
        toast.appendChild(content);

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
