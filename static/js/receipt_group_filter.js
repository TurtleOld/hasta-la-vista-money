console.log('receipt_group_filter loaded');

function initReceiptGroupSelect(selectedValue) {
    const groupSelect = document.getElementById('receipt-group-select');
    if (groupSelect) {
        if (!selectedValue && sessionStorage.getItem('selectedReceiptGroup')) {
            selectedValue = sessionStorage.getItem('selectedReceiptGroup');
        }
        if (selectedValue) {
            groupSelect.value = selectedValue;
        }
        groupSelect.onchange = null;
        groupSelect.addEventListener('change', function () {
            const groupId = this.value;
            sessionStorage.setItem('selectedReceiptGroup', groupId);
            const block = document.getElementById('receipts-block');
            if (block) {
                block.style.transition = 'opacity 0.3s';
                block.style.opacity = '0';
            }
            fetch(`/receipts/ajax/receipts_by_group/?group_id=${groupId}`)
                .then(response => response.json())
                .then(data => {
                    const block = document.getElementById('receipts-block');
                    if (block && data.html) {
                        setTimeout(() => {
                            block.innerHTML = data.html;
                            block.style.opacity = '1';
                        }, 300);
                    }
                });
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