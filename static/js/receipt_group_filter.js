function renderReceiptGroupBlock(data) {
    const block = document.getElementById('receipts-block');
    if (!block || !Array.isArray(data.receipts)) return;
    block.innerHTML = '';
    // --- Селектор групп ---
    const selectorRow = document.createElement('div');
    selectorRow.className = 'd-flex justify-content-between align-items-center mb-2 px-2 pt-2';
    const title = document.createElement('div');
    title.className = 'fw-bold';
    title.textContent = 'Чеки';
    selectorRow.appendChild(title);
    const selectWrap = document.createElement('div');
    selectWrap.className = 'ms-auto';
    const label = document.createElement('label');
    label.setAttribute('for', 'receipt-group-select');
    label.className = 'form-label mb-0';
    label.textContent = 'Группа чеков:';
    selectWrap.appendChild(label);
    const select = document.createElement('select');
    select.id = 'receipt-group-select';
    select.className = 'form-select form-select-sm';
    // Опция "Мои"
    const optMy = document.createElement('option');
    optMy.value = 'my';
    optMy.textContent = 'Мои';
    select.appendChild(optMy);
    // Группы пользователя
    if (Array.isArray(data.user_groups)) {
        data.user_groups.forEach(group => {
            const opt = document.createElement('option');
            opt.value = group.id;
            opt.textContent = group.name;
            select.appendChild(opt);
        });
    }
    // Восстановить выбранное значение
    const savedGroup = sessionStorage.getItem('selectedReceiptGroup');
    if (savedGroup) select.value = savedGroup;
    select.onchange = null;
    select.addEventListener('change', function () {
        const groupId = this.value;
        sessionStorage.setItem('selectedReceiptGroup', groupId);
        fetch(`/receipts/ajax/receipts_by_group/?group_id=${groupId}`)
            .then(response => response.json())
            .then(data => {
                renderReceiptGroupBlock(data);
            });
    });
    selectWrap.appendChild(select);
    selectorRow.appendChild(selectWrap);
    block.appendChild(selectorRow);
    // --- Конец селектора ---
    if (data.receipts.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'text-center text-muted py-3';
        empty.textContent = 'Чеки ещё не созданы!';
        block.appendChild(empty);
    } else {
        data.receipts.forEach(receipt => {
            // Показываем все чеки, выделяем только чужие
            let cardClass = 'card mb-2 shadow-sm';
            const isForeign = receipt.is_foreign === true;
            if (isForeign) {
                cardClass += ' receipt-foreign';
            }
            const card = document.createElement('div');
            card.className = cardClass;
            // card-body
            const cardBody = document.createElement('div');
            cardBody.className = 'card-body d-flex justify-content-between align-items-center';
            // Левая часть
            const left = document.createElement('div');
            const seller = document.createElement('div');
            seller.className = 'fw-semibold';
            seller.textContent = receipt.seller;
            left.appendChild(seller);
            const date = document.createElement('div');
            date.className = 'text-muted small';
            date.textContent = receipt.receipt_date;
            left.appendChild(date);
            const sumRow = document.createElement('div');
            sumRow.className = 'mt-1';
            const sum = document.createElement('span');
            sum.className = 'fw-bold text-success';
            sum.textContent = receipt.total_sum;
            sumRow.appendChild(sum);
            left.appendChild(sumRow);
            // Только для чужих чеков выводим владельца
            if (isForeign) {
                const owner = document.createElement('div');
                owner.className = 'receipt-owner-label';
                owner.textContent = 'Владелец: ' + receipt.owner;
                left.appendChild(owner);
            }
            // Товары (до 3)
            if (Array.isArray(receipt.products) && receipt.products.length > 0) {
                const productsDiv = document.createElement('div');
                productsDiv.className = 'products-preview mt-2';
                const productsLabel = document.createElement('small');
                productsLabel.className = 'text-muted';
                productsLabel.textContent = 'Товары:';
                productsDiv.appendChild(productsLabel);
                const tagsDiv = document.createElement('div');
                tagsDiv.className = 'product-tags';
                receipt.products.forEach(product => {
                    const tag = document.createElement('span');
                    tag.className = 'badge bg-light text-dark me-1 mb-1';
                    tag.textContent = product;
                    tagsDiv.appendChild(tag);
                });
                productsDiv.appendChild(tagsDiv);
                left.appendChild(productsDiv);
            }
            // Правая часть
            const right = document.createElement('div');
            right.className = 'd-flex flex-column align-items-end gap-1';
            const viewBtn = document.createElement('a');
            viewBtn.href = receipt.url;
            viewBtn.className = 'btn btn-outline-secondary btn-sm mb-1';
            viewBtn.title = 'Просмотр';
            viewBtn.innerHTML = '<i class="bi bi-eye me-1"></i>Просмотр';
            right.appendChild(viewBtn);
            // --- Кнопка удаления ---
            const form = document.createElement('form');
            form.className = 'm-0';
            form.method = 'post';
            form.action = `/receipts/${receipt.id}/`;
            const btn = document.createElement('button');
            btn.className = 'remove-object-button btn btn-outline-danger border-0 btn-sm';
            btn.type = 'submit';
            btn.name = 'delete_receipt_button';
            btn.title = 'Удалить чек';
            btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-trash" viewBox="0 0 16 16"><path d="M5.5 5.5A.5.5 0 0 1 6 6v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm2.5.5a.5.5 0 0 0-1 0v6a.5.5 0 0 0 1 0V6zm3 .5a.5.5 0 0 1 .5-.5.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6z"/><path fill-rule="evenodd" d="M14.5 3a1 1 0 0 1-1 1H13v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4h-.5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1H14a1 1 0 0 1 1 1v1zM4.118 4 4 4.059V13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.059L11.882 4H4.118zM2.5 3V2h11v1h-11z"/></svg>';
            form.appendChild(btn);
            right.appendChild(form);
            // --- Конец кнопки удаления ---
            cardBody.appendChild(left);
            cardBody.appendChild(right);
            card.appendChild(cardBody);
            block.appendChild(card);
        });
    }
}

function initReceiptGroupSelect(selectedValue) {
    const groupSelect = document.getElementById('receipt-group-select');
    if (groupSelect) {
        if (!selectedValue && sessionStorage.getItem('selectedReceiptGroup')) {
            selectedValue = sessionStorage.getItem('selectedReceiptGroup');
        }
        if (selectedValue) {
            groupSelect.value = selectedValue;
        }
        // Не вешаем обработчик здесь, он будет в renderReceiptGroupBlock
    } else {
        // Если селектор ещё не отрисован (например, при первой загрузке)
        // Получаем данные с сервера и рендерим всё
        const savedGroup = sessionStorage.getItem('selectedReceiptGroup') || 'my';
        fetch(`/receipts/ajax/receipts_by_group/?group_id=${savedGroup}`)
            .then(response => response.json())
            .then(data => {
                renderReceiptGroupBlock(data);
            });
    }
}

document.addEventListener('DOMContentLoaded', function () {
    initReceiptGroupSelect();

    // Если в sessionStorage выбранная группа не 'my', делаем редирект с параметром group_id
    const savedGroup = sessionStorage.getItem('selectedReceiptGroup');
    if (savedGroup && savedGroup !== 'my') {
        const url = new URL(window.location.href);
        if (url.searchParams.get('group_id') !== savedGroup) {
            url.searchParams.set('group_id', savedGroup);
            window.location.replace(url.toString());
        }
    }
});
