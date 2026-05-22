document.addEventListener('DOMContentLoaded', function () {
    const csrftoken = getCookie('csrftoken');
    const planningElements = document.querySelectorAll('.planning');

    let timeoutId;

    planningElements.forEach(function (planningElement) {
        planningElement.addEventListener('input', function () {
            if (timeoutId) {
                clearTimeout(timeoutId);
            }

            timeoutId = setTimeout(function () {
                const newPlanningValue = planningElement.textContent;
                const date = planningElement.closest('.date')?.id || '';
                const category = planningElement
                    .closest('tr')
                    ?.querySelector('td:first-child')
                    ?.textContent
                    .trim() || '';

                fetch('change-planning/', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrftoken || '',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    body: JSON.stringify({
                        planning: newPlanningValue,
                        date: date,
                        category: category,
                    }),
                }).catch(function (error) {
                    console.error('Planning update failed:', error);
                });
            }, 500);
        });
    });

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(
                        cookie.substring(name.length + 1),
                    );
                    break;
                }
            }
        }
        return cookieValue;
    }
});
