document.addEventListener('DOMContentLoaded', function() {
    const fabButton = document.getElementById('bottom-nav-fab');
    if (!fabButton) return;

    const currentPath = window.location.pathname;
    const incomeUrl = fabButton.dataset.incomeUrl;
    const expenseUrl = fabButton.dataset.expenseUrl;
    const incomeClasses = ['from-sky-500', 'to-cyan-400', 'shadow-sky-500/30'];
    const expenseClasses = ['from-emerald-600', 'to-emerald-400', 'shadow-emerald-600/30'];

    if (currentPath.includes('/income/') && !currentPath.includes('/budget/')) {
        fabButton.href = incomeUrl;
        fabButton.classList.remove(...expenseClasses);
        fabButton.classList.add(...incomeClasses);
    } else if (currentPath.includes('/expense/') && !currentPath.includes('/budget/')) {
        fabButton.href = expenseUrl;
        fabButton.classList.remove(...incomeClasses);
        fabButton.classList.add(...expenseClasses);
    } else {
        fabButton.href = expenseUrl;
        fabButton.classList.remove(...incomeClasses);
        fabButton.classList.add(...expenseClasses);
    }

    const fabIcon = document.getElementById('fab-icon');
    if (fabIcon) {
        if (fabButton.classList.contains('from-sky-500')) {
            fabIcon.className = 'bi bi-graph-up-arrow text-xl';
        } else {
            fabIcon.className = 'bi bi-graph-down-arrow text-xl';
        }
    }
});
