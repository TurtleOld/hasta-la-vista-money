(function() {
    'use strict';

    function setupModals() {
        document.querySelectorAll('.modal-open').forEach(button => {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                const modalId = this.getAttribute('data-modal');
                const modal = document.getElementById(modalId);
                if (modal) {
                    document.querySelectorAll('[id^="payment"], [id^="loan"]').forEach(m => {
                        m.classList.add('hidden');
                        m.classList.remove('flex');
                    });
                    modal.classList.remove('hidden');
                    modal.classList.add('flex');
                    document.body.style.overflow = 'hidden';

                    if (modalId === 'payment-options') {
                        function processMathJax() {
                            if (typeof window.MathJax !== 'undefined' && window.MathJax.typesetPromise) {
                                if (window.MathJax.typesetClear) {
                                    window.MathJax.typesetClear([modal]);
                                }
                                window.MathJax.typesetPromise([modal]).catch(function(err) {
                                    console.error('MathJax typeset error:', err);
                                });
                            } else if (typeof window.renderMathJax === 'function') {
                                window.renderMathJax(modal);
                            }
                        }

                        requestAnimationFrame(function() {
                            requestAnimationFrame(function() {
                                setTimeout(processMathJax, 100);
                            });
                        });
                    }
                }
            });
        });

        document.querySelectorAll('.modal-close').forEach(button => {
            button.addEventListener('click', function() {
                const modal = this.closest('[id^="payment"], [id^="loan"]');
                if (modal) {
                    modal.classList.add('hidden');
                    modal.classList.remove('flex');
                    document.body.style.overflow = '';
                }
            });
        });

        document.querySelectorAll('[id^="payment"], [id^="loan"]').forEach(modal => {
            modal.addEventListener('click', function(e) {
                if (e.target === this) {
                    this.classList.add('hidden');
                    this.classList.remove('flex');
                    document.body.style.overflow = '';
                }
            });
        });

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                document.querySelectorAll('[id^="payment"], [id^="loan"]').forEach(modal => {
                    if (!modal.classList.contains('hidden')) {
                        modal.classList.add('hidden');
                        modal.classList.remove('flex');
                        document.body.style.overflow = '';
                    }
                });
            }
        });
    }

    function setupDropdowns() {
        document.querySelectorAll('[data-dropdown]').forEach(dropdown => {
            const toggle = dropdown.querySelector('.dropdown-toggle');
            const menu = dropdown.querySelector('.dropdown-menu');
            if (toggle && menu) {
                toggle.addEventListener('click', function(e) {
                    e.stopPropagation();
                    menu.classList.toggle('hidden');
                });
                document.addEventListener('click', function(e) {
                    if (!dropdown.contains(e.target)) {
                        menu.classList.add('hidden');
                    }
                });
            }
        });
    }

    function setupAjaxForms() {
        document.querySelectorAll('.ajax-form').forEach(function(form) {
            form.addEventListener('submit', function(e) {
                const submitBtn = form.querySelector('button[type="submit"]');
                if (submitBtn) {
                    const originalHTML = submitBtn.innerHTML;
                    submitBtn.innerHTML = '<svg class="mr-2 inline h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>Загрузка...';
                    submitBtn.disabled = true;

                    fetch(form.action, {
                        method: 'POST',
                        body: new FormData(form),
                        headers: {
                            'X-CSRFToken': form.querySelector('[name=csrfmiddlewaretoken]').value
                        }
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            location.reload();
                        } else {
                            submitBtn.innerHTML = originalHTML;
                            submitBtn.disabled = false;
                            if (data.errors) {
                                Object.keys(data.errors).forEach(function(field) {
                                    const fieldElement = form.querySelector('[name=' + field + ']');
                                    if (fieldElement) {
                                        const errorDiv = document.createElement('p');
                                        errorDiv.className = 'mt-1 text-sm text-red-600 dark:text-red-400';
                                        errorDiv.textContent = data.errors[field][0];
                                        fieldElement.parentElement.appendChild(errorDiv);
                                    }
                                });
                            }
                        }
                    })
                    .catch(error => {
                        submitBtn.innerHTML = originalHTML;
                        submitBtn.disabled = false;
                        console.error('Error:', error);
                    });

                    e.preventDefault();
                }
            });
        });
    }

    document.addEventListener('DOMContentLoaded', function() {
        setupModals();
        setupDropdowns();
        setupAjaxForms();
    });
})();
