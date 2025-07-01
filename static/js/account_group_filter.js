function initAccountGroupSelect(selectedValue) {
    const groupSelect = document.getElementById('account-group-select');
    if (groupSelect) {
        if (!selectedValue && sessionStorage.getItem('selectedAccountGroup')) {
            selectedValue = sessionStorage.getItem('selectedAccountGroup');
        }
        if (selectedValue) {
            groupSelect.value = selectedValue;
        }
        groupSelect.onchange = null;
        groupSelect.addEventListener('change', function () {
            const groupId = this.value;
            sessionStorage.setItem('selectedAccountGroup', groupId);
            fetch(`/finance_account/ajax/accounts_by_group/?group_id=${groupId}`)
                .then(response => response.json())
                .then(data => {
                    const block = document.getElementById('account-cards-block');
                    if (block && data.html) {
                        block.outerHTML = data.html;
                        initAccountGroupSelect(groupId);
                    }
                });
        });
    }
}
document.addEventListener('DOMContentLoaded', function () {
    initAccountGroupSelect();

    // Если в sessionStorage выбранная группа не 'my', делаем редирект с параметром group_id
    const savedGroup = sessionStorage.getItem('selectedAccountGroup');
    if (savedGroup && savedGroup !== 'my') {
        const url = new URL(window.location.href);
        if (url.searchParams.get('group_id') !== savedGroup) {
            url.searchParams.set('group_id', savedGroup);
            window.location.replace(url.toString());
        }
    }
}); 