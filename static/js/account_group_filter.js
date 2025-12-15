function renderAccountGroupBlock(data) {
    const block = document.getElementById('account-cards-block');
    if (!block) return;
    
    block.innerHTML = '';
    block.className = 'space-y-3';
    
    if (!Array.isArray(data.accounts) || data.accounts.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'text-center py-12 px-4';
        const icon = document.createElement('div');
        icon.className = 'inline-flex items-center justify-center w-16 h-16 rounded-full bg-gray-100 dark:bg-gray-800 mb-4';
        icon.innerHTML = '<svg class="w-8 h-8 text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z"></path></svg>';
        empty.appendChild(icon);
        const text1 = document.createElement('p');
        text1.className = 'text-gray-500 dark:text-gray-400 text-lg font-medium';
        text1.textContent = 'Счета ещё не созданы!';
        empty.appendChild(text1);
        const text2 = document.createElement('p');
        text2.className = 'text-gray-400 dark:text-gray-500 text-sm mt-1';
        text2.textContent = 'Начните с добавления первого счёта';
        empty.appendChild(text2);
        block.appendChild(empty);
        return;
    }
    
    data.accounts.forEach(account => {
        const card = document.createElement('div');
        const isForeign = account.is_foreign || false;
        card.className = 'group bg-white dark:bg-gray-800 rounded-xl shadow-md hover:shadow-xl border border-gray-200 dark:border-gray-700 transition-all duration-300 overflow-hidden' + (isForeign ? ' account-foreign border-l-4 border-l-blue-500' : '');
        
        const cardBody = document.createElement('div');
        cardBody.className = 'p-5 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4';
        
        const left = document.createElement('div');
        left.className = 'flex-1 min-w-0';
        
        const nameRow = document.createElement('div');
        nameRow.className = 'flex items-center gap-2.5 mb-2';
        
        const name = document.createElement('h3');
        name.className = 'font-semibold text-lg text-gray-900 dark:text-white truncate';
        name.textContent = account.name_account;
        nameRow.appendChild(name);
        
        if (isForeign) {
            const ownerBadge = document.createElement('span');
            ownerBadge.className = 'inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 rounded-full';
            ownerBadge.innerHTML = '<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg><span>Владелец: ' + (account.owner || account.user_username || '') + '</span>';
            nameRow.appendChild(ownerBadge);
        }
        
        left.appendChild(nameRow);
        
        const type = document.createElement('div');
        type.className = 'text-sm text-gray-500 dark:text-gray-400 mb-2.5';
        type.textContent = account.type_account_display || account.type_account;
        left.appendChild(type);
        
        const balanceRow = document.createElement('div');
        balanceRow.className = 'flex items-baseline gap-2';
        const balance = document.createElement('span');
        balance.className = 'text-2xl font-bold text-gray-900 dark:text-white';
        balance.textContent = account.balance;
        balanceRow.appendChild(balance);
        const currency = document.createElement('span');
        currency.className = 'text-sm text-gray-500 dark:text-gray-400 font-medium';
        currency.textContent = account.currency;
        balanceRow.appendChild(currency);
        left.appendChild(balanceRow);
        
        const right = document.createElement('div');
        right.className = 'flex items-center gap-2 flex-shrink-0';
        
        const link = document.createElement('a');
        link.href = account.url || account.get_absolute_url || '#';
        link.className = 'change-object-button inline-flex items-center justify-center w-10 h-10 rounded-lg bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-all duration-200 active:scale-95 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 dark:focus:ring-offset-gray-800';
        link.title = 'Редактировать';
        link.innerHTML = '<svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path></svg>';
        right.appendChild(link);
        
        const form = document.createElement('form');
        form.className = 'm-0';
        form.method = 'post';
        form.action = account.delete_url || `/finance_account/delete/${account.id}/`;
        
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]');
        if (csrfToken) {
            const csrfInput = document.createElement('input');
            csrfInput.type = 'hidden';
            csrfInput.name = 'csrfmiddlewaretoken';
            csrfInput.value = csrfToken.value;
            form.appendChild(csrfInput);
        }
        
        const btn = document.createElement('button');
        btn.className = 'remove-object-button inline-flex items-center justify-center w-10 h-10 rounded-lg bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/50 transition-all duration-200 active:scale-95 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 dark:focus:ring-offset-gray-800';
        btn.type = 'submit';
        btn.name = 'delete_account_button';
        btn.title = 'Удалить счёт';
        btn.innerHTML = '<svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>';
        form.appendChild(btn);
        right.appendChild(form);
        
        cardBody.appendChild(left);
        cardBody.appendChild(right);
        card.appendChild(cardBody);
        block.appendChild(card);
    });
}

function loadAccountsBlock(groupId) {
    const params = new URLSearchParams(window.location.search);
    params.set('group_id', groupId);
    fetch('/api/finaccount/by-group/?' + params.toString(), {
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' }
    })
        .then(response => response.json())
        .then(data => {
            const accounts = data.results || data.accounts || [];
            const accountData = {
                accounts: accounts,
                user_groups: data.user_groups || []
            };
            renderAccountGroupBlock(accountData);
        })
        .catch(error => {
            console.error('Error loading account cards:', error);
        });
}

document.addEventListener('DOMContentLoaded', function () {
    const select = document.getElementById('account-group-select');
    if (select) {
        select.addEventListener('change', function () {
            const params = new URLSearchParams(window.location.search);
            params.set('group_id', this.value);
            const newUrl = window.location.pathname + '?' + params.toString();
            window.history.pushState({}, '', newUrl);

            loadAccountsBlock(this.value);
        });
    }
});
