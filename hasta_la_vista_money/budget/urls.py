from django.urls import path
from hasta_la_vista_money.budget.views import (
    BudgetView,
    change_planning,
    generate_date_list_view,
    save_planning,
)

app_name = 'budget'
urlpatterns = [
    path("", BudgetView.as_view(), name="list"),
    path("generate-date/", generate_date_list_view, name="generate_date"),
    path(
        "change_planning/",
        change_planning,
        name="change_planning",
    ),
    path("save-planning/", save_planning, name="save_planning"),
]
