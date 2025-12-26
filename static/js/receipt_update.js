(function() {
    function initReceiptUpdate() {
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

        const newPriceInput = newForm.querySelector('input[name*="price"]') || newForm.querySelector('input.price') || newForm.querySelector('.price input');
        const newQuantityInput = newForm.querySelector('input[name*="quantity"]') || newForm.querySelector('input.quantity') || newForm.querySelector('.quantity input');
        
        if (newPriceInput) {
            newPriceInput.addEventListener('input', amountUpdate);
            newPriceInput.addEventListener('change', amountUpdate);
            newPriceInput.addEventListener('blur', amountUpdate);
        }
        if (newQuantityInput) {
            newQuantityInput.addEventListener('input', amountUpdate);
            newQuantityInput.addEventListener('change', amountUpdate);
            newQuantityInput.addEventListener('blur', amountUpdate);
        }
    }

    function removeForm(e) {
        e.preventDefault();
        if (container.children.length > 1) {
            container.removeChild(container.lastElementChild);
            formNum--;
            totalForms.setAttribute('value', `${formNum + 1}`);
            calculateTotalSum();
        }
    }

    function amountUpdate(event) {
        try {
            const input = event ? event.target : this;
            const form = input.closest('.form-product');
            if (!form) {
                console.warn('Receipt update: form not found');
                return;
            }

            const priceInput = form.querySelector('input[name*="price"]') || form.querySelector('input.price') || form.querySelector('.price input');
            const quantityInput = form.querySelector('input[name*="quantity"]') || form.querySelector('input.quantity') || form.querySelector('.quantity input');
            const amountInput = form.querySelector('input[name*="amount"]') || form.querySelector('input.amount') || form.querySelector('.amount input');

            if (!priceInput || !quantityInput || !amountInput) {
                console.warn('Receipt update: inputs not found', {
                    price: !!priceInput,
                    quantity: !!quantityInput,
                    amount: !!amountInput
                });
                return;
            }

            const price = parseFloat(String(priceInput.value).replace(',', '.').replace(/\s/g, '')) || 0;
            const quantity = parseFloat(String(quantityInput.value).replace(',', '.').replace(/\s/g, '')) || 0;
            const amount = (price * quantity).toFixed(2);
            
            amountInput.value = amount;
            amountInput.dispatchEvent(new Event('change', { bubbles: true }));

            calculateTotalSum();
        } catch (error) {
            console.error('Receipt update error:', error);
        }
    }

    function calculateTotalSum() {
        const totalSumInput = document.getElementById('id_total_sum');
        const amountInputs = document.querySelectorAll('input[name*="amount"]');
        let total_sum = 0;

        amountInputs.forEach(amountInput => {
            const value = String(amountInput.value).replace(',', '.').replace(/\s/g, '');
            total_sum += parseFloat(value) || 0;
        });

        if (totalSumInput) {
            totalSumInput.value = total_sum.toFixed(2);
        }
    }

    function attachEventListeners() {
        const priceInputs = container.querySelectorAll('input[name*="price"]');
        const quantityInputs = container.querySelectorAll('input[name*="quantity"]');
        
        [...priceInputs, ...quantityInputs].forEach(input => {
            input.removeEventListener('input', amountUpdate);
            input.removeEventListener('change', amountUpdate);
            input.removeEventListener('blur', amountUpdate);
            input.addEventListener('input', amountUpdate);
            input.addEventListener('change', amountUpdate);
            input.addEventListener('blur', amountUpdate);
        });
    }

    attachEventListeners();

    container.querySelectorAll('.form-product').forEach(form => {
        const priceInput = form.querySelector('input[name*="price"]') || form.querySelector('input.price') || form.querySelector('.price input');
        const quantityInput = form.querySelector('input[name*="quantity"]') || form.querySelector('input.quantity') || form.querySelector('.quantity input');
        const amountInput = form.querySelector('input[name*="amount"]') || form.querySelector('input.amount') || form.querySelector('.amount input');
        
        if (priceInput && quantityInput && amountInput) {
            const price = parseFloat(String(priceInput.value).replace(',', '.').replace(/\s/g, '')) || 0;
            const quantity = parseFloat(String(quantityInput.value).replace(',', '.').replace(/\s/g, '')) || 0;
            if (price > 0 && quantity > 0) {
                const amount = (price * quantity).toFixed(2);
                amountInput.value = amount;
            }
        }
    });

    calculateTotalSum();

    const form = document.querySelector('form[method="post"]');
    if (form) {
        form.addEventListener('submit', function() {
            calculateTotalSum();
        });
    }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initReceiptUpdate);
    } else {
        initReceiptUpdate();
    }
})();
