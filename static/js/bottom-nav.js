document.addEventListener('DOMContentLoaded', function() {
    const fabButton = document.getElementById('bottom-nav-fab');
    if (!fabButton) return;

    const currentPath = window.location.pathname;
    const incomeUrl = fabButton.dataset.incomeUrl;
    const expenseUrl = fabButton.dataset.expenseUrl;

    if (currentPath.includes('/income/') && !currentPath.includes('/budget/')) {
        fabButton.href = incomeUrl;
        fabButton.classList.add('fab-income');
    } else if (currentPath.includes('/expense/') && !currentPath.includes('/budget/')) {
        fabButton.href = expenseUrl;
        fabButton.classList.add('fab-expense');
    } else {
        fabButton.href = expenseUrl;
        fabButton.classList.add('fab-expense');
    }

    const fabIcon = document.getElementById('fab-icon');
    if (fabIcon) {
        if (fabButton.classList.contains('fab-income')) {
            fabIcon.className = 'bi bi-graph-up-arrow';
        } else {
            fabIcon.className = 'bi bi-graph-down-arrow';
        }
    }
});
