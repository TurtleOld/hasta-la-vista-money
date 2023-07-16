$(document).ready(function() {
    $(document).on('submit', '.ajax-form', function(event) {
        event.preventDefault();  // Отмена обычной отправки формы
        let form = $(this);
        $.ajax({
            url: form.attr('action'),
            type: 'POST',
            data: form.serialize(),  // Сериализация данных формы
            success: function(response) {
                if (response.success) {
                    // Обработка успешного ответа
                    location.reload()
                } else {
                    const errors = response.errors
                    console.log(errors)
                    if (errors) {
                        form.find('.has-error').removeClass('has-error'); // Удаляем класс has-error у всех полей формы
                        form.find('.help-block').remove(); // Удаляем все предыдущие сообщения об ошибках
                        for (let field in errors) {
                            if (errors.hasOwnProperty(field)) {
                                const fieldErrors = errors[field];
                                const fieldElement = form.find('[name="' + field + '"]');
                                const errorContainer = fieldElement.closest('.form-group');
                                errorContainer.addClass('has-error');
                                for (let i = 0; i < fieldErrors.length; i++) {
                                    let errorMessage = '<p class="help-block text-danger">' + fieldErrors[i] + '</p>';
                                    errorContainer.append(errorMessage);
                                }
                            }
                        }
                    }
                }
            },
            error: function(xhr) {
                // Обработка ошибки запроса
                const errorMessage = 'Произошла ошибка при отправке запроса. Пожалуйста, повторите попытку позже или измените запрос.';
                $('#error-message').text(errorMessage);
                $('.ajax-modal').modal('hide');
                $('#errorModal').modal('show');

            }
        });
    });
});