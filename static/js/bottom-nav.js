document.addEventListener('DOMContentLoaded', function() {
    const fabButton = document.getElementById('bottom-nav-fab');
    if (!fabButton) return;

    const currentPath = window.location.pathname;
    const incomeUrl = fabButton.dataset.incomeUrl;
    const expenseUrl = fabButton.dataset.expenseUrl;
    const incomeClasses = ['from-sky-500', 'to-cyan-400', 'shadow-sky-500/30'];
    const expenseClasses = ['from-emerald-600', 'to-emerald-400', 'shadow-emerald-600/30'];

    function setFabIcon(type) {
        const fabIcon = document.getElementById('fab-icon');
        if (!fabIcon) return;

        if (type === 'income') {
            fabIcon.innerHTML = '<svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 3v18h18M7 14l3-3 3 3 5-6"></path></svg>';
            return;
        }

        fabIcon.innerHTML = '<svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v8m-4-4h8"></path></svg>';
    }

    if (currentPath.includes('/income/') && !currentPath.includes('/budget/')) {
        fabButton.href = incomeUrl;
        fabButton.classList.remove(...expenseClasses);
        fabButton.classList.add(...incomeClasses);
        setFabIcon('income');
    } else if (currentPath.includes('/expense/') && !currentPath.includes('/budget/')) {
        fabButton.href = expenseUrl;
        fabButton.classList.remove(...incomeClasses);
        fabButton.classList.add(...expenseClasses);
        setFabIcon('expense');
    } else {
        fabButton.href = expenseUrl;
        fabButton.classList.remove(...incomeClasses);
        fabButton.classList.add(...expenseClasses);
        setFabIcon('expense');
    }
});
