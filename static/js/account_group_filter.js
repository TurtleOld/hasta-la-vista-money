function renderAccountGroupBlock(data) {
    const block = document.getElementById('account-cards-block');
    if (!block || !Array.isArray(data.accounts)) return;
    // --- Селектор групп ---
    block.innerHTML = '';
    const selectorRow = document.createElement('div');
    selectorRow.className = 'd-flex justify-content-between align-items-center mb-2 px-2 pt-2';
    const title = document.createElement('div');
    title.className = 'fw-bold';
    title.textContent = 'Счета';
    selectorRow.appendChild(title);
    const selectWrap = document.createElement('div');
    selectWrap.className = 'ms-auto';
    const label = document.createElement('label');
    label.setAttribute('for', 'account-group-select');
    label.className = 'form-label mb-0';
    label.textContent = 'Группа счетов:';
    selectWrap.appendChild(label);
    const select = document.createElement('select');
    select.id = 'account-group-select';
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
    // Выставить значение селектора по query-параметру
    const url = new URL(window.location.href);
    const groupId = url.searchParams.get('group_id') || 'my';
    select.value = groupId;
    select.onchange = null;
    select.addEventListener('change', function () {
        const selectedGroup = this.value;
        // Обновить URL
        const params = new URLSearchParams(window.location.search);
        params.set('group_id', selectedGroup);
        const newUrl = window.location.pathname + '?' + params.toString();
        window.history.pushState({}, '', newUrl);
        // Подгрузить счета через AJAX
        loadAccountsBlock(selectedGroup);
    });
    selectWrap.appendChild(select);
    selectorRow.appendChild(selectWrap);
    block.appendChild(selectorRow);
    // --- Конец селектора ---
    if (data.accounts.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'text-center text-muted py-3';
        empty.textContent = 'Счета ещё не созданы!';
        block.appendChild(empty);
    } else {
        data.accounts.forEach(account => {
            const card = document.createElement('div');
            card.className = 'card mb-2 shadow-sm' + (account.is_foreign ? ' account-foreign' : '');
            // card-body
            const cardBody = document.createElement('div');
            cardBody.className = 'card-body d-flex justify-content-between align-items-center';
            // Левая часть
            const left = document.createElement('div');
            const name = document.createElement('div');
            name.className = 'fw-semibold';
            name.textContent = account.name_account;
            left.appendChild(name);
            const type = document.createElement('div');
            type.className = 'type-account text-muted small';
            type.textContent = account.type_account;
            left.appendChild(type);
            const balanceRow = document.createElement('div');
            balanceRow.className = 'mt-1';
            const balance = document.createElement('span');
            balance.className = 'fw-bold';
            balance.textContent = account.balance;
            balanceRow.appendChild(balance);
            const currency = document.createElement('span');
            currency.className = 'text-muted';
            currency.textContent = ' ' + account.currency;
            balanceRow.appendChild(currency);
            left.appendChild(balanceRow);
            if (account.is_foreign) {
                const owner = document.createElement('div');
                owner.className = 'account-owner-label';
                owner.textContent = 'Владелец: ' + account.owner;
                left.appendChild(owner);
            }
            // Правая часть
            const right = document.createElement('div');
            right.className = 'd-flex flex-column align-items-end gap-1';
            const link = document.createElement('a');
            link.href = account.url;
            link.className = 'change-object-button btn btn-outline-primary border-0 btn-sm mb-1';
            link.title = 'Изменить';
            link.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-pencil-fill" viewBox="0 0 16 16"><path d="M12.854.146a.5.5 0 0 0-.707 0L10.5 1.793 14.207 5.5l1.647-1.646a.5.5 0 0 0 0-.708l-3-3zm.646 6.061L9.793 2.5 3.293 9H3.5a.5.5 0 0 1 .5.5v.5h.5a.5.5 0 0 1 .5.5v.5h.5a.5.5 0 0 1 .5.5v.5h.5a.5.5 0 0 1 .5.5v.207l6.5-6.5zm-7.468 7.468A.5.5 0 0 1 6 13.5V13h-.5a.5.5 0 0 1-.5-.5V12h-.5a.5.5 0 0 1-.5-.5V11h-.5a.5.5 0 0 1-.5-.5V10h-.5a.499.499 0 0 1-.175-.032l-.179.178a.5.5 0 0 0-.11.168l-2 5a.5.5 0 0 0 .65.65l5-2a.5.5 0 0 0 .168-.11l.178-.178z"></path></svg>`;
            right.appendChild(link);
            // --- Кнопка удаления ---
            const form = document.createElement('form');
            form.className = 'm-0';
            form.method = 'post';
            form.action = `/finance_account/delete/${account.id}`;
            const btn = document.createElement('button');
            btn.className = 'remove-object-button btn btn-outline-danger border-0 btn-sm';
            btn.type = 'submit';
            btn.name = 'delete_account_button';
            btn.title = 'Удалить счёт';
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

function loadAccountsBlock(groupId) {
    const params = new URLSearchParams(window.location.search);
    params.set('group_id', groupId);
    fetch('/finance_account/ajax/accounts_by_group/?' + params.toString(), {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
        .then(response => response.text())
        .then(html => {
            const block = document.querySelector('#account-cards-block');
            if (block) {
                const parser = new DOMParser();
                const doc = parser.parseFromString(html, 'text/html');  // eslint-disable-line
                const newContent = doc.body.firstElementChild;
                if (newContent) {
                    block.replaceWith(newContent);
                }
            }
        });
}

document.addEventListener('DOMContentLoaded', function () {
    const select = document.getElementById('account-group-select');
    if (select) {
        select.addEventListener('change', function () {
            // Обновляем group_id в URL
            const params = new URLSearchParams(window.location.search);
            params.set('group_id', this.value);
            const newUrl = window.location.pathname + '?' + params.toString();
            window.history.pushState({}, '', newUrl);

            loadAccountsBlock(this.value);
        });
    }
});
