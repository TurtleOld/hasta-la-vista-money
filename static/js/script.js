document.addEventListener('DOMContentLoaded', function() {
    onClickRemoveObject();

    const productInput = document.getElementById('product-autocomplete');
    let dropdown;
    let results = [];
    let currentFocus = -1;

    function showDropdown(items) {
        if (!productInput) return;
        closeDropdown();
        if (!items.length) return;
        dropdown = document.createElement('div');
        dropdown.className = 'dropdown-menu show w-100';
        dropdown.style.position = 'absolute';
        dropdown.style.top = productInput.offsetTop + productInput.offsetHeight + 'px';
        dropdown.style.left = productInput.offsetLeft + 'px';
        dropdown.style.zIndex = 1051;
        items.forEach(item => {
            const option = document.createElement('button');
            option.type = 'button';
            option.className = 'dropdown-item';
            option.textContent = item;
            option.onclick = function () {
                if (productInput) {
                    productInput.value = item;
                }
                closeDropdown();
            };
            dropdown.appendChild(option);
        });
        if (productInput.parentNode) {
            productInput.parentNode.appendChild(dropdown);
        }
        currentFocus = -1;
    }

    function closeDropdown() {
        if (dropdown) dropdown.remove();
        dropdown = null;
        currentFocus = -1;
    }

    function addActive(items) {
        if (!items.length) return;
        removeActive(items);

        if (typeof currentFocus !== 'number' || isNaN(currentFocus)) {
            currentFocus = 0;
        }

        if (currentFocus >= items.length) currentFocus = 0;
        if (currentFocus < 0) currentFocus = items.length - 1;

        if (typeof currentFocus === 'number' && !isNaN(currentFocus) &&
            currentFocus >= 0 && currentFocus < items.length) {
            const targetItem = Array.prototype.at.call(items, currentFocus);
            if (targetItem && typeof targetItem.classList !== 'undefined') {
                targetItem.classList.add('active');
            }
        }
    }

    function removeActive(items) {
        items.forEach(item => item.classList.remove('active'));
    }

    if (productInput) {
        productInput.addEventListener('input', async function () {
            const query = this.value.trim();
            if (query.length < 2) {
                closeDropdown();
                return;
            }
            try {
                const response = await fetchWithAuth(`/receipts/api/product-autocomplete/?q=${encodeURIComponent(query)}`);
                if (!response.ok) return;
                const data = await response.json();
                results = data.results || [];
                showDropdown(results);
            } catch (e) {
                closeDropdown();
            }
        });

        productInput.addEventListener('keydown', function (e) {
            const items = dropdown ? dropdown.querySelectorAll('.dropdown-item') : [];
            if (e.key === 'ArrowDown') {
                if (typeof currentFocus !== 'number' || isNaN(currentFocus)) {
                    currentFocus = -1;
                }
                currentFocus++;
                addActive(items);
            } else if (e.key === 'ArrowUp') {
                if (typeof currentFocus !== 'number' || isNaN(currentFocus)) {
                    currentFocus = items.length;
                }
                currentFocus--;
                addActive(items);
            } else if (e.key === 'Enter') {
                e.preventDefault();

                if (typeof currentFocus === 'number' && !isNaN(currentFocus) &&
                    currentFocus > -1 && currentFocus < items.length) {
                    const targetItem = Array.prototype.at.call(items, currentFocus);
                    if (targetItem && typeof targetItem.click === 'function') {
                        targetItem.click();
                    }
                }
            }
        });

        document.addEventListener('click', function (e) {
            if (e.target !== productInput) closeDropdown();
        });
    }

    const loginForm = document.querySelector('form.form');
    if (loginForm && window.location.pathname.includes('login')) {
        loginForm.addEventListener('submit', async function (e) {
            e.preventDefault();

            const formAction = loginForm.action;
            if (!formAction || typeof formAction !== 'string') {
                window.toast.error('Ошибка: неверный URL формы');
                return;
            }

            try {
                const urlObj = new URL(formAction, window.location.origin);
                if (urlObj.origin !== window.location.origin) {
                    window.toast.error('Ошибка: неверный URL формы');
                    return;
                }
            } catch (e) {
                window.toast.error('Ошибка: неверный формат URL');
                return;
            }

            const formData = new FormData(loginForm);
            const response = await fetch(formAction, {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'include'
            });

            if (response.status === 429) {
                if (response.headers.get('content-type')?.includes('application/json')) {
                    const data = await response.json();
                    if (data.error) {
                        window.toast.error(data.error);
                    } else {
                        window.toast.error('Слишком много неудачных попыток входа. Ваш браузер и компьютер заблокированы для входа в это приложение. Попробуйте позже или обратитесь к администратору.');
                    }
                } else {
                    window.toast.error('Слишком много неудачных попыток входа. Ваш браузер и компьютер заблокированы для входа в это приложение. Попробуйте позже или обратитесь к администратору.');
                }
                return;
            }

            if (response.status >= 400 && response.status < 500) {
                window.toast.error('Произошла ошибка при входе. Попробуйте еще раз.');
                window.location.reload();
                return;
            }

            if (response.status >= 500) {
                window.toast.error('Произошла ошибка на сервере. Попробуйте позже.');
                window.location.reload();
                return;
            }

            if (response.headers.get('content-type')?.includes('application/json')) {
                const data = await response.json();
                if (data.redirect_url) {
                    try {
                        const redirectUrl = new URL(data.redirect_url, window.location.origin);
                        if (redirectUrl.origin !== window.location.origin) {
                            window.toast.error('Ошибка: неверный URL редиректа');
                            return;
                        }
                        window.location.replace(redirectUrl.pathname + redirectUrl.search + redirectUrl.hash);
                    } catch (e) {
                        window.toast.error('Ошибка: неверный формат URL редиректа');
                        return;
                    }
                } else if (data.success === false) {
                    if (data.error) {
                        window.toast.error(data.error);
                    } else if (data.errors) {
                        const errorMessages = Object.values(data.errors).filter(msg => msg);
                        if (errorMessages.length > 0) {
                            window.toast.error(errorMessages.join(', '));
                        } else {
                            window.toast.error('Ошибка входа. Проверьте данные.');
                        }
                    } else {
                        window.toast.error('Ошибка входа. Проверьте данные.');
                    }
                } else {
                    window.location.reload();
                }
            } else {
                window.location.reload();
            }
        });
    }

    let productForm = document.querySelectorAll(".form-product");
    let container = document.querySelector("#form-create-receipt");
    let addButton = document.querySelector("#add-form");
    let removeButton = document.querySelector("#remove-form");
    let totalForms = document.querySelector("#id_form-TOTAL_FORMS");

    let formNum = productForm.length-1;
    if (addButton) addButton.addEventListener('click', addForm);
    if (removeButton) removeButton.addEventListener('click', removeForm);

    function addForm(e) {
        e.preventDefault();
        if (!container || !productForm.length || !addButton || !totalForms) return;

        let newForm = productForm[0].cloneNode(true);
        let formRegex = RegExp(`form-(\\d){1}-`,'g');
        formNum++;

        const formElements = newForm.querySelectorAll('input, select, textarea, label');
        formElements.forEach(element => {
            if (element.name) {
                element.name = element.name.replace(formRegex, 'form-' + formNum + '-');
            }
            if (element.id) {
                element.id = element.id.replace(formRegex, 'form-' + formNum + '-');
            }
            if (element.hasAttribute('for')) {
                const currentFor = element.getAttribute('for');
                const newFor = currentFor.replace(formRegex, 'form-' + formNum + '-');
                element.setAttribute('for', newFor);
            }
        });

        container.insertBefore(newForm, addButton);
        totalForms.setAttribute('value', `${formNum+1}`);

        const priceInput = newForm.querySelector('.price');
        const quantityInput = newForm.querySelector('.quantity');
        if (priceInput) priceInput.addEventListener('input', amountUpdate);
        if (quantityInput) quantityInput.addEventListener('input', amountUpdate);
    }

    function removeForm(e) {
        e.preventDefault();
        if (!totalForms) return;

        productForm = document.querySelectorAll(".form-product");
        if (productForm.length <= 1) return;

        let lastForm = productForm[productForm.length - 1];
        let formRegex = RegExp(`form-(\\d){1}-`,'g');

        const formElements = lastForm.querySelectorAll('input, select, textarea, label');
        formElements.forEach(element => {
            if (element.name) {
                element.name = element.name.replace(formRegex, 'form-' + (productForm.length - 1) + '-');
            }
            if (element.id) {
                element.id = element.id.replace(formRegex, 'form-' + (productForm.length - 1) + '-');
            }
            if (element.hasAttribute('for')) {
                const currentFor = element.getAttribute('for');
                const newFor = currentFor.replace(formRegex, 'form-' + (productForm.length - 1) + '-');
                element.setAttribute('for', newFor);
            }
        });

        lastForm.remove();
        totalForms.setAttribute('value', `${productForm.length - 1}`);
    }

    function amountUpdate() {
        if (!container) return;

        let formInputs = container.querySelectorAll('.form-product');
        formInputs.forEach( formInput => {
            let priceInput = formInput.querySelector('.price');
            let quantityInput = formInput.querySelector('.quantity');
            let amountInput = formInput.querySelector('.amount');
            if (priceInput && quantityInput && amountInput) {
                let price = parseFloat(priceInput.value.replace(',', '.')) || 0;
                let quantity = parseFloat(quantityInput.value.replace(',', '.')) || 0;
                let amount = price * quantity;
                amountInput.value = amount.toFixed(2);
            }
        });
    }

    productForm.forEach(form => {
        const priceInput = form.querySelector('.price');
        const quantityInput = form.querySelector('.quantity');
        if (priceInput) priceInput.addEventListener('input', amountUpdate);
        if (quantityInput) quantityInput.addEventListener('input', amountUpdate);
    });

    function calculateTotalSum() {
        let totalSumInput = document.getElementById('id_total_sum');
        let amountInputs = document.querySelectorAll('.amount');
        let total_sum = 0;

        amountInputs.forEach(amountInput => {
            total_sum += parseFloat(amountInput.value.replace(',', '.')) || 0;
        });

        if (totalSumInput) {
            totalSumInput.value = total_sum.toFixed(2);
        }
    }

    const formCreateReceipt = document.getElementById('form-create-receipt');
    if (formCreateReceipt) {
        formCreateReceipt.addEventListener('input', calculateTotalSum);
    }

    if (window.location.pathname.includes('/receipts')) {
        window.tokens.ensureValidAccessToken().then(valid => {
            if (valid) {
                window.tokens.scheduleAccessTokenRefresh();
            } else {
                window.tokens.refreshTokensIfNeeded().then(refreshed => {
                    if (refreshed) {
                        window.tokens.scheduleAccessTokenRefresh();
                    }
                });
            }
        });
    }

    const deleteForm = document.getElementById('delete-user-from-group-form');
    if (deleteForm) {
        const userSelect = deleteForm.querySelector('select[name="user"]');
        const groupSelect = deleteForm.querySelector('select[name="group"]');

        userSelect.addEventListener('change', function () {
            const userId = this.value;
            groupSelect.innerHTML = '<option value="">Загрузка...</option>';
            fetch(`${window.GROUPS_FOR_USER_URL}?user_id=${userId}`)
                .then(response => response.json())
                .then(data => {
                    groupSelect.innerHTML = '';
                    if (data.groups.length === 0) {
                        groupSelect.innerHTML = '<option value="">Нет доступных групп</option>';
                    } else {
                        data.groups.forEach(function (group) {
                            const option = document.createElement('option');
                            option.value = group.id;
                            option.textContent = group.name;
                            groupSelect.appendChild(option);
                        });
                    }
                });
        });
    }

    const addUserForm = document.getElementById('add-user-to-group-form');
    if (addUserForm) {
        const userSelect = addUserForm.querySelector('select[name="user"]');
        const groupSelect = addUserForm.querySelector('select[name="group"]');

        userSelect.addEventListener('change', function () {
            const userId = this.value;
            groupSelect.innerHTML = '<option value="">Загрузка...</option>';
            fetch(`${window.GROUPS_NOT_FOR_USER_URL}?user_id=${userId}`)
                .then(response => response.json())
                .then(data => {
                    groupSelect.innerHTML = '';
                    if (data.groups.length === 0) {
                        groupSelect.innerHTML = '<option value="">Нет доступных групп</option>';
                    } else {
                        data.groups.forEach(function (group) {
                            const option = document.createElement('option');
                            option.value = group.id;
                            option.textContent = group.name;
                            groupSelect.appendChild(option);
                        });
                    }
                });
        });
    }

    window.setTimeout(function () {
        $(".alert").fadeTo(400, 0).slideUp(400, function () {
            $(this).remove();
        });
    }, 4000);

    function onClickRemoveObject() {
        const removeObjectButton = document.querySelectorAll('.remove-object-button')
        removeObjectButton.forEach((button) => {
            button.addEventListener('click', (event) => {
                const confirmed_button_category = confirm('Вы уверены?')
                if (!confirmed_button_category) {
                    event.preventDefault()
                }
            });
        });
    }

    function ultraSafeFetch(path, options = {}) {
        if (!path || typeof path !== 'string') {
            throw new Error('Invalid path provided');
        }

        const cleanPath = path.replace(/[^a-zA-Z0-9\-_/.?=&]/g, '');

        if (!cleanPath.startsWith('/')) {
            throw new Error('Path must start with /');
        }

        const allowedPaths = [
            '/receipts/api/product-autocomplete/',
            '/authentication/token/refresh/',
            '/authentication/token/session/',
            '/users/login/'
        ];

        const isAllowed = allowedPaths.some(allowedPath => cleanPath.startsWith(allowedPath));
        if (!isAllowed) {
            throw new Error('Path not allowed');
        }

        const safeFetch = (url, opts) => {
            if (url === '/receipts/api/product-autocomplete/') {
                return fetch('/receipts/api/product-autocomplete/', opts);
            } else if (url === '/authentication/token/refresh/') {
                return fetch('/authentication/token/refresh/', opts);
            } else if (url === '/authentication/token/session/') {
                return fetch('/authentication/token/session/', opts);
            } else if (url === window.LOGIN_URL) {
                return fetch(window.LOGIN_URL, opts);
            } else {
                throw new Error('Unsafe URL detected');
            }
        };

        return safeFetch(cleanPath, options);
    }

    async function fetchWithAuth(url, options = {}) {
        if (!url || typeof url !== 'string') {
            throw new Error('Invalid URL provided');
        }
        try {
            const urlObj = new URL(url, window.location.origin);
            if (urlObj.origin !== window.location.origin) {
                throw new Error('URL must be from the same origin');
            }
            const path = urlObj.pathname + urlObj.search + urlObj.hash;

            options.credentials = 'include';

            let response = await ultraSafeFetch(path, options);

            if (response.status === 401) {
                const refreshResp = await fetch('/authentication/token/refresh/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include'
                });
                if (refreshResp.ok) {
                    return ultraSafeFetch(path, options);
                } else {
                    try {
                        const sessionResponse = await fetch(window.location.pathname, {
                            method: 'GET',
                            credentials: 'include',
                            headers: { 'X-Requested-With': 'XMLHttpRequest' }
                        });

                        if (sessionResponse.ok) {
                            const refreshed = await window.tokens.refreshTokensIfNeeded();
                            if (refreshed) {
                                return ultraSafeFetch(path, options);
                            } else {
                                return response;
                            }
                        }

                        if (sessionResponse.status === 302) {
                            window.toast.warning('Ваша сессия истекла. Пожалуйста, войдите снова.');
                            window.location.replace(window.LOGIN_URL);
                            return response;
                        }
                    } catch (e) {
                        return response;
                    }

                    return response;
                }
            }
            return response;
        } catch (e) {
            throw new Error('Invalid URL format');
        }
    }
});
