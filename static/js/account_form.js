(function() {
    'use strict';

    var initialized = false;

    function handleAccountTypeChange() {
        var typeSelect = document.getElementById('id_type_account');
        if (!typeSelect) {
            return;
        }

        var selectedValue = typeSelect.value;
        var isCredit = selectedValue === 'CreditCard' || selectedValue === 'Credit';
        var creditFields = document.querySelectorAll('[data-credit-field="true"]');

        creditFields.forEach(function(field) {
            if (isCredit) {
                field.classList.add('show');
            } else {
                field.classList.remove('show');
            }
        });
    }

    function init() {
        if (initialized) {
            return;
        }

        var form = document.getElementById('add-account-form') || document.getElementById('change-account-form');
        if (!form) {
            return;
        }

        var typeSelect = document.getElementById('id_type_account');
        if (!typeSelect) {
            return;
        }

        typeSelect.addEventListener('change', handleAccountTypeChange);
        handleAccountTypeChange();
        initialized = true;
    }

    function tryInit() {
        if (document.getElementById('id_type_account')) {
            init();
        }
    }

    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        tryInit();
    } else {
        document.addEventListener('DOMContentLoaded', tryInit);
    }

    window.addEventListener('load', tryInit);
})();

