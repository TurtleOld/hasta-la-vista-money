$(function () {
    function recalcRowAndTotals(cell) {
        var row = cell.closest('tr');
        var colIdx = cell.index();
        var monthIdx = Math.floor((colIdx - 1) / 4);
        if (monthIdx < 0) return;
        var factCell = row.find('td').eq(1 + monthIdx * 4);
        var planCell = row.find('td').eq(1 + monthIdx * 4 + 1);
        var diffCell = row.find('td').eq(1 + monthIdx * 4 + 2);
        var percentCell = row.find('td').eq(1 + monthIdx * 4 + 3);
        var fact = parseFloat(factCell.text().replace(',', '.')) || 0;
        var plan = parseFloat(planCell.text().replace(',', '.')) || 0;
        var diff = fact - plan;
        var percent = plan ? (fact / plan * 100) : null;
        diffCell.text(diff ? diff.toFixed(2) : '—');
        percentCell.text(percent ? percent.toFixed(0) + '%' : '—');
        diffCell.removeClass('delta-negative delta-positive');
        if (diff < 0) diffCell.addClass('delta-negative');
        else if (diff > 0) diffCell.addClass('delta-positive');
        var table = cell.closest('table');
        var totalFact = 0, totalPlan = 0;
        table.find('tbody tr').each(function () {
            var tds = $(this).find('td');
            totalFact += parseFloat(tds.eq(1 + monthIdx * 4).text().replace(',', '.')) || 0;
            totalPlan += parseFloat(tds.eq(1 + monthIdx * 4 + 1).text().replace(',', '.')) || 0;
        });
        var tfoot = table.find('tfoot tr th, tfoot tr td');
        var base = 1 + monthIdx * 4;
        tfoot.eq(base).text(totalFact ? totalFact.toFixed(2) : '—');
        tfoot.eq(base + 1).text(totalPlan ? totalPlan.toFixed(2) : '—');
        var tDiff = totalFact - totalPlan;
        tfoot.eq(base + 2).text(tDiff ? tDiff.toFixed(2) : '—');
        tfoot.eq(base + 3).text(totalPlan ? (totalFact / totalPlan * 100).toFixed(0) + '%' : '—');
    }
    $('.plan-cell').on('input', function () {
        recalcRowAndTotals($(this));
    });
    $('.plan-cell').on('blur', function () {
        var cell = $(this);
        var amount = parseFloat(cell.text().replace(',', '.')) || 0;
        var category = cell.data('category');
        var category_id = cell.data('category-id');
        var month = cell.data('month');
        var type = cell.data('type');
        var url = cell.data('save-url') || '/budget/save-planning/';
        var csrf = cell.data('csrf') || $('input[name=csrfmiddlewaretoken]').val();
        $.ajax({
            url: url,
            type: 'POST',
            data: JSON.stringify({
                amount: amount,
                category_id: category_id,
                month: month,
                type: type
            }),
            contentType: 'application/json',
            headers: { 'X-CSRFToken': csrf },
            success: function (resp) {
                if (resp.success) {
                    cell.addClass('table-success');
                    setTimeout(function () { cell.removeClass('table-success'); }, 1000);
                    recalcRowAndTotals(cell);
                } else {
                    cell.addClass('table-danger');
                }
            },
            error: function () {
                cell.addClass('table-danger');
            }
        });
    });
});
