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
                    location.reload()
                    form[0].reset()
                } else {
                    const errors = response.errors
                    if (errors) {
                        form.find('.has-error').removeClass('has-error'); // Удаляем класс has-error у всех полей формы
                        form.find('.help-block').remove(); // Удаляем все предыдущие сообщения об ошибках
                        for (let field in errors) {
                            if (errors.hasOwnProperty(field)) {
                                const fieldErrors = errors[field];
                                if ('quantity' in fieldErrors) {
                                    for (let fieldError in fieldErrors) {
                                        const fieldElement = form.find('[name="form-' + field + '-' + fieldError +'"]');
                                        const errorContainer = fieldElement.closest('.form-group');
                                        errorContainer.addClass('has-error');
                                        let errorMessage = '<p class="help-block text-danger">' + fieldErrors[fieldError] + '</p>';
                                        errorContainer.append(errorMessage);
                                    }
                                }
                                else {
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
                }
            },
            error: function (xhr) {
                const errorMessage = 'Произошла ошибка при отправке запроса. Пожалуйста, повторите попытку позже или измените запрос.';
                $('#error-message').text(errorMessage);
                $('.ajax-modal').modal('hide');
                $('#errorModal').modal('show');

            }
        });
    });
});
