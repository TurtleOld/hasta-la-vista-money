$(document).ready(function () {
    const csrftoken = getCookie('csrftoken');
    const planningElements = $(".planning");

    let timeoutId;

    planningElements.on("input", function () {
        if (timeoutId) {
            clearTimeout(timeoutId);
        }

        timeoutId = setTimeout(() => {
            const planningCell = $(this);
            const newPlanningValue = planningCell.text();
            const date = planningCell.closest('.date').attr('id');
            const category = planningCell.closest("tr").find("td:first-child").text().trim();

            console.log("Data:", { planning: newPlanningValue, date, category });

            $.ajax({
                url: 'change-planning/',
                type: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    "X-CSRFToken": csrftoken,
                },
                data: JSON.stringify({ planning: newPlanningValue, date, category }),
                dataType: 'json',
                success: function (data) {
                    console.log('Success: ', data);
                },
                error: function (xhr, textStatus, errorThrown) {
                    console.error('AJAX Error: ', xhr, textStatus, errorThrown);
                    console.log('Server Response Text: ', xhr.responseText); // Log the actual response
                },
            });
        }, 500); // Adjust the timeout value as needed
    });

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
});
