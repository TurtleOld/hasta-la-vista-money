(function () {
    const budgetFormSelector = '.budget-plan-form, .budget-limit-form';

    document.addEventListener('submit', (event) => {
        if (event.target.matches(budgetFormSelector)) {
            event.preventDefault();
        }
    });
}());
