document.addEventListener('DOMContentLoaded', function () {
    document.addEventListener('submit', function (event) {
        const form = event.target.closest('.ajax-form');
        if (!form) {
            return;
        }

        event.preventDefault();
        submitAjaxForm(form);
    });
});

async function submitAjaxForm(form) {
    try {
        const response = await fetch(form.action, {
            method: 'POST',
            body: new URLSearchParams(new FormData(form)),
            credentials: 'same-origin',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
            },
        });

        if (!response.ok) {
            showRequestError();
            return;
        }

        const data = await response.json();
        if (data.success) {
            window.location.reload();
            form.reset();
            return;
        }

        renderFormErrors(form, data.errors);
    } catch (error) {
        console.error('AJAX form submit failed:', error);
        showRequestError();
    }
}

function renderFormErrors(form, errors) {
    if (!errors) {
        return;
    }

    form.querySelectorAll('.has-error').forEach(function (element) {
        element.classList.remove('has-error');
    });
    form.querySelectorAll('.help-block').forEach(function (element) {
        element.remove();
    });

    Object.entries(errors).forEach(function ([field, fieldErrors]) {
        if (fieldErrors && Object.hasOwn(fieldErrors, 'quantity')) {
            Object.entries(fieldErrors).forEach(function ([fieldError, message]) {
                const fieldElement = form.querySelector(
                    '[name="form-' + field + '-' + fieldError + '"]',
                );
                appendFieldError(fieldElement, message);
            });
            return;
        }

        const fieldElement = form.querySelector('[name="' + field + '"]');
        const messages = Array.isArray(fieldErrors) ? fieldErrors : [fieldErrors];
        messages.forEach(function (message) {
            appendFieldError(fieldElement, message);
        });
    });
}

function appendFieldError(fieldElement, message) {
    const errorContainer = fieldElement?.closest('.form-group');
    if (!errorContainer) {
        return;
    }

    errorContainer.classList.add('has-error');
    const errorMessage = document.createElement('p');
    errorMessage.className = 'help-block text-danger';
    errorMessage.textContent = String(message);
    errorContainer.appendChild(errorMessage);
}

function showRequestError() {
    const errorMessage = 'Произошла ошибка при отправке запроса. Пожалуйста, повторите попытку позже или измените запрос.';
    const errorMessageElement = document.getElementById('error-message');
    if (errorMessageElement) {
        errorMessageElement.textContent = errorMessage;
    }

    document.querySelectorAll('.ajax-modal').forEach(function (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('show');
    });

    const errorModal = document.getElementById('errorModal');
    if (errorModal && window.bootstrap?.Modal) {
        window.bootstrap.Modal.getOrCreateInstance(errorModal).show();
        return;
    }

    if (window.toast) {
        window.toast.error(errorMessage);
    }
}
