let productForm = document.querySelectorAll(".form-product")
let container = document.querySelector("#form-create-receipt")
let addButton = document.querySelector("#add-form")
let removeButton = document.querySelector("#remove-form")
let totalForms = document.querySelector("#id_form-TOTAL_FORMS")


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
                alert('Ошибка: неверный URL формы');
                return;
            }

            try {
                const urlObj = new URL(formAction, window.location.origin);
                if (urlObj.origin !== window.location.origin) {
                    alert('Ошибка: неверный URL формы');
                    return;
                }
            } catch (e) {
                alert('Ошибка: неверный формат URL');
                return;
            }

            const formData = new FormData(loginForm);
            const response = await fetch(formAction, {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            if (response.headers.get('content-type')?.includes('application/json')) {
                const data = await response.json();
                if (data.access && data.refresh && data.redirect_url) {
                    localStorage.setItem('access_token', data.access);
                    localStorage.setItem('refresh_token', data.refresh);

                    try {
                        const redirectUrl = new URL(data.redirect_url, window.location.origin);
                        if (redirectUrl.origin !== window.location.origin) {
                            alert('Ошибка: неверный URL редиректа');
                            return;
                        }
                        window.location.replace(redirectUrl.pathname + redirectUrl.search + redirectUrl.hash);
                    } catch (e) {
                        alert('Ошибка: неверный формат URL редиректа');
                        return;
                    }
                } else {
                    alert('Ошибка входа. Проверьте логин и пароль.');
                }
            } else {
                window.location.reload();
            }
        });
    }
});

window.setTimeout(function() {
    $(".alert").fadeTo(400, 0).slideUp(400, function(){
        $(this).remove();
    });
}, 4000);

let formNum = productForm.length-1
addButton.addEventListener('click', addForm)
removeButton.addEventListener('click', removeForm)

function addForm(e) {
    e.preventDefault()

    let newForm = productForm[0].cloneNode(true)
    let formRegex = RegExp(`form-(\\d){1}-`,'g')

    formNum++
    newForm.innerHTML = newForm.innerHTML.replace(formRegex, `form-${formNum}-`)
    container.insertBefore(newForm, addButton)

    totalForms.setAttribute('value', `${formNum+1}`)
    newForm.querySelector('.price').addEventListener('input', amountUpdate);
    newForm.querySelector('.quantity').addEventListener('input', amountUpdate);
}

function removeForm(e) {
    e.preventDefault()

    productForm = document.querySelectorAll(".form-product")
    let lastForm = productForm[productForm.length - 1]

    let formRegex = RegExp(`form-(\\d){1}-`,'g')
    lastForm.innerHTML = lastForm.innerHTML.replace(formRegex, `form-${productForm.length - 1}-`);

    if (productForm.length > 1) {
        lastForm.remove();
    }

    totalForms.setAttribute('value', `${productForm.length}`)

}

function amountUpdate() {
    let formInputs = container.querySelectorAll('.form-product');
    formInputs.forEach( formInput => {
        let priceInput = formInput.querySelector('.price');
        let quantityInput = formInput.querySelector('.quantity');
        let amountInput = formInput.querySelector('.amount');
        if (priceInput && quantityInput && amountInput) {
            let price = parseFloat(priceInput.value);
            let quantity = parseFloat(quantityInput.value);
            let amount = price * quantity;
            amountInput.value = amount.toFixed(2);
        }
    });
}

productForm.forEach(form => {
    form.querySelector('.price').addEventListener('input', amountUpdate);
    form.querySelector('.quantity').addEventListener('input', amountUpdate);
});


function calculateTotalSum() {
    let totalSumInput = document.getElementById('id_total_sum');
    let amountInputs = document.querySelectorAll('.amount');
    let total_sum = 0;

    amountInputs.forEach(amountInput => {
      total_sum += parseFloat(amountInput.value);
    });

    totalSumInput.value = total_sum.toFixed(2);
  }

document.getElementById('form-create-receipt').addEventListener('input', calculateTotalSum);

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
        } else if (url === '/users/login/') {
            return fetch('/users/login/', opts);
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

        let token = localStorage.getItem('access_token');
        if (!options.headers) options.headers = {};
        if (token) options.headers['Authorization'] = 'Bearer ' + token;

        let response = await ultraSafeFetch(path, options);

        if (response.status === 401) {
            const refresh = localStorage.getItem('refresh_token');
            if (refresh) {
                const refreshResp = await fetch('/authentication/token/refresh/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ refresh })
                });
                if (refreshResp.ok) {
                    const data = await refreshResp.json();
                    localStorage.setItem('access_token', data.access);
                    options.headers['Authorization'] = 'Bearer ' + data.access;
                    return ultraSafeFetch(path, options);
                } else {
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('refresh_token');
                    alert('Ваша сессия истекла. Пожалуйста, войдите снова.');
                    window.location.replace('/users/login/');
                    return response;
                }
            }
        }
        return response;
    } catch (e) {
        throw new Error('Invalid URL format');
    }
}

async function checkAndRefreshTokensOnLoad() {
    const access = localStorage.getItem('access_token');
    const refresh = localStorage.getItem('refresh_token');

    if (!access || !refresh) {
        console.log('Токены не найдены в localStorage');
        return;
    }

    const payload = parseJwt(access);
    if (!payload || !payload.exp) {
        console.log('Не удалось декодировать access token');
        return;
    }

    const now = Math.floor(Date.now() / 1000);
    const secondsLeft = payload.exp - now;

    console.log(`Токен истечёт через ${secondsLeft} секунд`);

    if (secondsLeft <= 300) {
        console.log('Обновляем токены...');
        try {
            const resp = await fetch('/authentication/token/refresh/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh })
            });
            if (resp.ok) {
                const data = await resp.json();
                localStorage.setItem('access_token', data.access);
                if (data.refresh) {
                    localStorage.setItem('refresh_token', data.refresh);
                }
                console.log('Токены обновлены автоматически');
            } else {
                localStorage.removeItem('access_token');
                localStorage.removeItem('refresh_token');
                console.log('Сессия истекла, токены очищены');
            }
        } catch (e) {
            console.log('Ошибка при обновлении токенов:', e);
        }
    } else {
        console.log('Токен ещё действителен, обновление не требуется');
    }
}

function parseJwt(token) {
    try {
        const base64Url = token.split('.')[1];
        const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
        const jsonPayload = decodeURIComponent(atob(base64).split('').map(function (c) {
            return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }).join(''));
        return JSON.parse(jsonPayload);
    } catch (e) {
        return null;
    }
}

function scheduleAccessTokenRefresh() {
    const access = localStorage.getItem('access_token');
    const refresh = localStorage.getItem('refresh_token');
    if (!access || !refresh) return;

    const payload = parseJwt(access);
    if (!payload || !payload.exp) return;

    const now = Math.floor(Date.now() / 1000);
    const secondsLeft = payload.exp - now;
    const refreshIn = (secondsLeft - 30) * 1000;
    if (refreshIn <= 0) {
        doRefreshToken();
    } else {
        setTimeout(doRefreshToken, refreshIn);
    }
}

async function doRefreshToken() {
    const refresh = localStorage.getItem('refresh_token');
    if (!refresh) {
        console.log('Refresh token не найден');
        return;
    }
    try {
        console.log('Выполняем плановое обновление токенов...');
        const resp = await fetch('/authentication/token/refresh/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh })
        });
        if (resp.ok) {
            const data = await resp.json();
            localStorage.setItem('access_token', data.access);
            if (data.refresh) {
                localStorage.setItem('refresh_token', data.refresh);
            }
            console.log('Токены успешно обновлены');
            scheduleAccessTokenRefresh();
        } else {
            console.log('Ошибка при обновлении токенов, очищаем сессию');
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            if (document.hasFocus()) {
                alert('Ваша сессия истекла. Пожалуйста, войдите снова.');
                window.location.replace('/users/login/');
            }
        }
    } catch (e) {
        console.log('Сетевая ошибка при обновлении токенов:', e);
        setTimeout(doRefreshToken, 10000);
    }
}

document.addEventListener('DOMContentLoaded', function () {
    checkAndRefreshTokensOnLoad();
    scheduleAccessTokenRefresh();
});
