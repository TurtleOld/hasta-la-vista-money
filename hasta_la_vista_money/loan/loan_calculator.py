def calculate_annuity_schedule(
    amount: float,
    annual_rate: float,
    months: int,
) -> dict:
    """
    Возвращает график платежей для аннуитетного кредита с банковским округлением (до рубля).
    Последний платёж = остаток долга + проценты, округлённый до рубля.
    :param amount: сумма кредита
    :param annual_rate: годовая ставка в процентах (например, 12)
    :param months: срок кредита в месяцах
    :return: dict с ключами:
        - 'schedule': список платежей (dict: месяц, платёж, проценты, основной долг, остаток)
        - 'total_payment': общая сумма выплат
        - 'overpayment': переплата
        - 'monthly_payment': размер ежемесячного платежа (округлённый)
    """
    monthly_rate = annual_rate / 100 / 12
    payment_raw = (
        amount
        * (monthly_rate * (1 + monthly_rate) ** months)
        / ((1 + monthly_rate) ** months - 1)
        if monthly_rate
        else amount / months
    )
    schedule = []
    payments = []
    remaining = amount
    for i in range(1, months):
        payment = round(payment_raw, 2)
        interest = remaining * monthly_rate
        principal = payment - round(interest, 2)
        schedule.append(
            {
                'month': i,
                'payment': payment,
                'interest': round(interest, 2),
                'principal': round(principal, 2),
                'balance': max(0, round(remaining - principal, 2)),
            },
        )
        payments.append(payment)
        remaining -= principal
    interest = remaining * monthly_rate
    last_payment = round(remaining + interest, 2)
    schedule.append(
        {
            'month': months,
            'payment': last_payment,
            'interest': round(interest, 2),
            'principal': round(remaining, 2),
            'balance': 0,
        },
    )
    payments.append(last_payment)
    total_payment = sum(payments)
    overpayment = total_payment - amount
    return {
        'schedule': schedule,
        'total_payment': total_payment,
        'overpayment': round(overpayment, 2),
        'monthly_payment': round(payment_raw, 2),
    }


def calculate_differentiated_schedule(
    amount: float,
    annual_rate: float,
    months: int,
) -> dict:
    """
    Возвращает график платежей для дифференцированного кредита с банковским округлением (до рубля).
    :param amount: сумма кредита
    :param annual_rate: годовая ставка в процентах (например, 12)
    :param months: срок кредита в месяцах
    :return: dict с ключами:
        - 'schedule': список платежей (dict: месяц, платёж, проценты, основной долг, остаток)
        - 'total_payment': общая сумма выплат
        - 'overpayment': переплата
    """
    monthly_rate = annual_rate / 100 / 12
    principal_payment = amount / months
    schedule = []
    total_payment = 0
    remaining = amount
    for i in range(1, months + 1):
        interest = remaining * monthly_rate
        payment = principal_payment + interest
        payment_rounded = round(payment, 2)
        total_payment += payment_rounded
        schedule.append(
            {
                'month': i,
                'payment': payment_rounded,
                'interest': round(interest, 2),
                'principal': round(principal_payment, 2),
                'balance': max(0, round(remaining - principal_payment, 2)),
            },
        )
        remaining -= principal_payment
    overpayment = total_payment - amount
    return {
        'schedule': schedule,
        'total_payment': total_payment,
        'overpayment': round(overpayment, 2),
    }
