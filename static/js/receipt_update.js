document.addEventListener('DOMContentLoaded', function() {
    const container = document.getElementById('product-forms');
    const addButton = document.getElementById('add-form');
    const removeButton = document.getElementById('remove-form');
    const totalForms = document.querySelector('[name="form-TOTAL_FORMS"]');

    if (!container || !addButton || !removeButton || !totalForms) {
        return;
    }

    let formNum = container.children.length - 1;

    if (addButton) addButton.addEventListener('click', addForm);
    if (removeButton) removeButton.addEventListener('click', removeForm);

    function addForm(e) {
        e.preventDefault();
        let newForm = container.children[0].cloneNode(true);
        let formRegex = RegExp(`form-(\\d){1}-`,'g');
        formNum++;

        const formElements = newForm.querySelectorAll('input, select, textarea, label');
        formElements.forEach(element => {
            if (element.name) {
                element.name = element.name.replace(formRegex, 'form-' + formNum + '-');
            }
            if (element.id) {
                element.id = element.id.replace(formRegex, 'form-' + formNum + '-');
            }
            if (element.hasAttribute('for')) {
                const currentFor = element.getAttribute('for');
                const newFor = currentFor.replace(formRegex, 'form-' + formNum + '-');
                element.setAttribute('for', newFor);
            }
        });

        newForm.querySelectorAll('input[type="text"], input[type="number"]').forEach(input => {
            input.value = '';
        });

        container.appendChild(newForm);
        totalForms.setAttribute('value', `${formNum + 1}`);

        newForm.querySelector('.price')?.addEventListener('input', amountUpdate);
        newForm.querySelector('.quantity')?.addEventListener('input', amountUpdate);
    }

    function removeForm(e) {
        e.preventDefault();
        if (container.children.length > 1) {
            container.removeChild(container.lastElementChild);
            formNum--;
            totalForms.setAttribute('value', `${formNum + 1}`);
        }
    }

    function amountUpdate() {
        const form = this.closest('.form-product');
        const priceInput = form.querySelector('.price');
        const quantityInput = form.querySelector('.quantity');
        const amountInput = form.querySelector('.amount');

        if (priceInput && quantityInput && amountInput) {
            const price = parseFloat(priceInput.value.replace(',', '.')) || 0;
            const quantity = parseFloat(quantityInput.value.replace(',', '.')) || 0;
            amountInput.value = (price * quantity).toFixed(2);
        }

        calculateTotalSum();
    }

    function calculateTotalSum() {
        const totalSumInput = document.getElementById('id_total_sum');
        const amountInputs = document.querySelectorAll('.amount');
        let total_sum = 0;

        amountInputs.forEach(amountInput => {
            total_sum += parseFloat(amountInput.value.replace(',', '.')) || 0;
        });

        if (totalSumInput) {
            totalSumInput.value = total_sum.toFixed(2);
        }
    }

    container.querySelectorAll('.price, .quantity').forEach(input => {
        input.addEventListener('input', amountUpdate);
    });

    calculateTotalSum();

    const form = document.querySelector('form[method="post"]');
    if (form) {
        form.addEventListener('submit', function() {
            calculateTotalSum();
        });
    }
});
