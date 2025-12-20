(function() {
    'use strict';

    function setupModals() {
        function processMathJax(modal) {
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
                        requestAnimationFrame(function() {
                            requestAnimationFrame(function() {
                                setTimeout(function() {
                                    processMathJax(modal);
                                }, 100);
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
                    const originalNodes = Array.from(submitBtn.childNodes).map(function(node) {
                        return node.cloneNode(true);
                    });

                    while (submitBtn.firstChild) {
                        submitBtn.removeChild(submitBtn.firstChild);
                    }
                    submitBtn.disabled = true;

                    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                    svg.className.baseVal = 'mr-2 inline h-4 w-4 animate-spin';
                    svg.setAttributeNS(null, 'fill', 'none');
                    svg.setAttributeNS(null, 'viewBox', '0 0 24 24');
                    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                    circle.className.baseVal = 'opacity-25';
                    circle.setAttributeNS(null, 'cx', '12');
                    circle.setAttributeNS(null, 'cy', '12');
                    circle.setAttributeNS(null, 'r', '10');
                    circle.setAttributeNS(null, 'stroke', 'currentColor');
                    circle.setAttributeNS(null, 'stroke-width', '4');
                    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                    path.className.baseVal = 'opacity-75';
                    path.setAttributeNS(null, 'fill', 'currentColor');
                    path.setAttributeNS(null, 'd', 'M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z');
                    svg.appendChild(circle);
                    svg.appendChild(path);

                    submitBtn.appendChild(svg);
                    submitBtn.appendChild(document.createTextNode('Загрузка...'));

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
                            while (submitBtn.firstChild) {
                                submitBtn.removeChild(submitBtn.firstChild);
                            }
                            originalNodes.forEach(function(node) {
                                submitBtn.appendChild(node);
                            });
                            submitBtn.disabled = false;
                            if (data.errors) {
                                const allowedFieldNames = new Set(
                                    Array.from(form.elements)
                                        .map(function(el) {
                                            return el && el.name ? el.name : '';
                                        })
                                        .filter(Boolean),
                                );

                                const escapeCss =
                                    typeof CSS !== 'undefined' &&
                                    CSS &&
                                    typeof CSS.escape === 'function'
                                        ? CSS.escape.bind(CSS)
                                        : function(value) {
                                              return String(value).replace(
                                                  /[^a-zA-Z0-9_-]/g,
                                                  '\\$&',
                                              );
                                          };

                                Object.keys(data.errors).forEach(function(field) {
                                    if (!allowedFieldNames.has(field)) {
                                        return;
                                    }

                                    const selector =
                                        '[name="' + escapeCss(field) + '"]';
                                    const fieldElement = form.querySelector(
                                        selector,
                                    );
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
                        while (submitBtn.firstChild) {
                            submitBtn.removeChild(submitBtn.firstChild);
                        }
                        originalNodes.forEach(function(node) {
                            submitBtn.appendChild(node);
                        });
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
