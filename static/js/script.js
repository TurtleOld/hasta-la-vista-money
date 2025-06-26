let productForm = document.querySelectorAll(".form-product")
let container = document.querySelector("#form-create-receipt")
let addButton = document.querySelector("#add-form")
let removeButton = document.querySelector("#remove-form")
let totalForms = document.querySelector("#id_form-TOTAL_FORMS")


document.addEventListener('DOMContentLoaded', function() {
    onClickRemoveObject();

    // --- Autocomplete for product field in receipts filter ---
    const productInput = document.getElementById('product-autocomplete');
    if (productInput) {
        let dropdown;
        let results = [];
        let currentFocus = -1;

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
                // Ошибка сети или токена
                closeDropdown();
            }
        });

        productInput.addEventListener('keydown', function (e) {
            const items = dropdown ? dropdown.querySelectorAll('.dropdown-item') : [];
            if (e.key === 'ArrowDown') {
                currentFocus++;
                addActive(items);
            } else if (e.key === 'ArrowUp') {
                currentFocus--;
                addActive(items);
            } else if (e.key === 'Enter') {
                e.preventDefault();
                if (currentFocus > -1 && items[currentFocus]) {
                    items[currentFocus].click();
                }
            }
        });

        document.addEventListener('click', function (e) {
            if (e.target !== productInput) closeDropdown();
        });

        function showDropdown(items) {
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
                    productInput.value = item;
                    closeDropdown();
                };
                dropdown.appendChild(option);
            });
            productInput.parentNode.appendChild(dropdown);
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
            if (currentFocus >= items.length) currentFocus = 0;
            if (currentFocus < 0) currentFocus = items.length - 1;
            items[currentFocus].classList.add('active');
        }
        function removeActive(items) {
            items.forEach(item => item.classList.remove('active'));
        }
    }

    // --- AJAX filter submit for receipts filter ---
    // const filterForm = document.getElementById('receipts-filter-form');
    // if (filterForm) {
    //     filterForm.addEventListener('submit', function (e) {
    //         e.preventDefault();
    //         const formData = new FormData(filterForm);
    //         const params = new URLSearchParams();
    //         for (const [key, value] of formData.entries()) {
    //             if (value) params.append(key, value);
    //         }
    //         fetch(window.location.pathname + '?' + params.toString(), {
    //             headers: { 'X-Requested-With': 'XMLHttpRequest' }
    //         })
    //             .then(response => response.text())
    //             .then(html => {
    //                 // Обновляем только список чеков (контейнер после фильтра)
    //                 const parser = new DOMParser();
    //                 const doc = parser.parseFromString(html, 'text/html');
    //                 const newContent = doc.querySelector('.container');
    //                 if (newContent) {
    //                     document.querySelector('.container').replaceWith(newContent);
    //                 } else {
    //                     window.location.reload();
    //                 }
    //             });
    //     });
    // }
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

// --- JWT fetch with refresh support ---
async function fetchWithAuth(url, options = {}) {
    let token = localStorage.getItem('access_token');
    if (!options.headers) options.headers = {};
    if (token) options.headers['Authorization'] = 'Bearer ' + token;

    let response = await fetch(url, options);

    if (response.status === 401) {
        // Попробовать обновить access token
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
                // Повторить исходный запрос с новым access token
                options.headers['Authorization'] = 'Bearer ' + data.access;
                return fetch(url, options);
            } else {
                // refresh тоже невалиден — разлогинить пользователя
                localStorage.removeItem('access_token');
                localStorage.removeItem('refresh_token');
                alert('Ваша сессия истекла. Пожалуйста, войдите снова.');
                window.location.href = '/users/login/';
                return response;
            }
        }
    }
    return response;
}
