const readJsonScript = (id) => {
  const element = document.getElementById(id);
  if (!element) {
    return [];
  }

  const content = element.textContent.trim();
  if (!content) {
    return [];
  }

  try {
    return JSON.parse(content);
  } catch (_error) {
    return [];
  }
};

const getTheme = () => {
  const bodyTheme = document.body.getAttribute('data-bs-theme');
  const htmlTheme = document.documentElement.getAttribute('data-bs-theme');

  if (bodyTheme === 'dark' || htmlTheme === 'dark') {
    return 'dark';
  }
  if (bodyTheme === 'light' || htmlTheme === 'light') {
    return 'light';
  }
  if (
    document.documentElement.classList.contains('dark') ||
    document.body.classList.contains('dark')
  ) {
    return 'dark';
  }
  if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }
  return 'light';
};

const emptyState = (title, hint = '') => {
  const hintHtml = hint ? `<p class="text-sm mt-2">${hint}</p>` : '';
  return `<div class="text-center py-8 text-gray-500 dark:text-gray-400"><p>${title}</p>${hintHtml}</div>`;
};

const openFinances = (config, params) => {
  if (!config.dataset.financesUrl) {
    return;
  }

  const url = new URL(config.dataset.financesUrl, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach((item) => url.searchParams.append(key, item));
    } else if (value) {
      url.searchParams.set(key, value);
    }
  });
  window.location.href = url.toString();
};

document.addEventListener('DOMContentLoaded', () => {
  if (typeof Chart === 'undefined') {
    return;
  }

  const config = document.getElementById('reportsChartConfig');
  if (!config) {
    return;
  }

  const chartLabels = readJsonScript('chartLabels');
  const chartIncome = readJsonScript('chartIncome');
  const chartExpense = readJsonScript('chartExpense');
  const chartBalance = readJsonScript('chartBalance');
  const pieLabels = readJsonScript('pieLabels');
  const pieValues = readJsonScript('pieValues');
  const chartStartDates = readJsonScript('chartStartDates');
  const chartEndDates = readJsonScript('chartEndDates');
  const pieCategoryKeys = readJsonScript('pieCategoryKeys');

  const budgetChartEl = document.getElementById('budgetChart');
  const balanceChartEl = document.getElementById('balanceChart');
  const pieChartEl = document.getElementById('pieChart');

  if (!chartLabels.length) {
    const noCharts = emptyState(
      config.dataset.noChartsTitle,
      config.dataset.noChartsHint,
    );
    [budgetChartEl, balanceChartEl, pieChartEl].forEach((element) => {
      if (element) {
        element.parentElement.innerHTML = noCharts;
      }
    });
    return;
  }

  if (!budgetChartEl || !balanceChartEl) {
    return;
  }

  const isDarkMode = getTheme() === 'dark';
  const textColor = isDarkMode ? '#e5e7eb' : '#111827';
  const gridColor = isDarkMode
    ? 'rgba(255, 255, 255, 0.1)'
    : 'rgba(0, 0, 0, 0.1)';
  const borderColor = isDarkMode
    ? 'rgba(255, 255, 255, 0.2)'
    : 'rgba(0, 0, 0, 0.2)';

  const commonOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top',
        labels: {
          color: textColor,
          padding: 15,
          font: { size: 13, weight: '500' },
          usePointStyle: false,
        },
      },
      tooltip: {
        backgroundColor: isDarkMode
          ? 'rgba(31, 41, 55, 0.95)'
          : 'rgba(255, 255, 255, 0.95)',
        titleColor: textColor,
        bodyColor: textColor,
        borderColor,
        borderWidth: 1,
        padding: 12,
        cornerRadius: 8,
        displayColors: true,
      },
    },
  };

  const monthClickParams = (index, type = 'all') => ({
    type,
    date_from: chartStartDates[index],
    date_to: chartEndDates[index],
  });

  new Chart(budgetChartEl.getContext('2d'), {
    type: 'bar',
    data: {
      labels: chartLabels,
      datasets: [
        {
          label: config.dataset.incomeLabel,
          data: chartIncome,
          backgroundColor: 'rgba(34, 197, 94, 0.7)',
          borderColor: 'rgba(34, 197, 94, 1)',
          borderWidth: 2,
          borderRadius: 6,
          borderSkipped: false,
        },
        {
          label: config.dataset.expenseLabel,
          data: chartExpense,
          backgroundColor: 'rgba(239, 68, 68, 0.7)',
          borderColor: 'rgba(239, 68, 68, 1)',
          borderWidth: 2,
          borderRadius: 6,
          borderSkipped: false,
        },
      ],
    },
    options: {
      ...commonOptions,
      onClick: (_event, elements) => {
        const element = elements[0];
        if (!element) {
          return;
        }
        openFinances(
          config,
          monthClickParams(
            element.index,
            element.datasetIndex === 0 ? 'income' : 'expense',
          ),
        );
      },
      scales: {
        x: {
          grid: { color: gridColor, drawBorder: false },
          ticks: { color: textColor, font: { size: 11 } },
        },
        y: {
          beginAtZero: true,
          grid: { color: gridColor, drawBorder: false },
          ticks: {
            color: textColor,
            font: { size: 11 },
            callback: (value) => value.toLocaleString('ru-RU'),
          },
        },
      },
    },
  });

  if (chartBalance.length) {
    const minBalance = Math.min(...chartBalance);
    const maxBalance = Math.max(...chartBalance);
    const range = maxBalance - minBalance;
    const padding = range > 0 ? range * 0.1 : Math.abs(minBalance) * 0.1 || 100;

    new Chart(balanceChartEl.getContext('2d'), {
      type: 'line',
      data: {
        labels: chartLabels,
        datasets: [
          {
            label: config.dataset.balanceLabel,
            data: chartBalance,
            borderColor: minBalance < 0 ? 'rgba(239, 68, 68, 1)' : 'rgba(34, 197, 94, 1)',
            backgroundColor: minBalance < 0 ? 'rgba(239, 68, 68, 0.1)' : 'rgba(34, 197, 94, 0.1)',
            borderWidth: 3,
            fill: true,
            tension: 0.4,
            pointBackgroundColor: minBalance < 0 ? 'rgba(239, 68, 68, 1)' : 'rgba(34, 197, 94, 1)',
            pointBorderColor: isDarkMode ? '#1f2937' : '#ffffff',
            pointBorderWidth: 2,
            pointRadius: 5,
            pointHoverRadius: 7,
            segment: {
              borderColor: (ctx) => {
                const value = ctx.p1.parsed.y;
                if (value < 0) return 'rgba(239, 68, 68, 1)';
                if (value > 0) return 'rgba(34, 197, 94, 1)';
                return 'rgba(59, 130, 246, 1)';
              },
            },
          },
        ],
      },
      options: {
        ...commonOptions,
        onClick: (_event, elements) => {
          const element = elements[0];
          if (element) {
            openFinances(config, monthClickParams(element.index));
          }
        },
        scales: {
          x: {
            grid: { color: gridColor, drawBorder: false },
            ticks: { color: textColor, font: { size: 11 } },
          },
          y: {
            beginAtZero: false,
            min: minBalance - padding,
            max: maxBalance + padding,
            grid: {
              color: (context) => context.tick.value === 0 ? borderColor : gridColor,
              lineWidth: (context) => context.tick.value === 0 ? 2 : 1,
              drawBorder: false,
            },
            ticks: {
              color: textColor,
              font: { size: 11 },
              callback: (value) => `${value >= 0 ? '+' : ''}${value.toLocaleString('ru-RU')}`,
            },
          },
        },
        plugins: {
          ...commonOptions.plugins,
          tooltip: {
            ...commonOptions.plugins.tooltip,
            callbacks: {
              label: (context) => {
                const value = context.parsed.y;
                const sign = value >= 0 ? '+' : '';
                return `${config.dataset.balanceTooltipLabel} ${sign}${value.toLocaleString('ru-RU', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}`;
              },
            },
          },
        },
      },
    });
  } else {
    balanceChartEl.parentElement.innerHTML = emptyState(config.dataset.noBalanceTitle);
  }

  if (!pieChartEl) {
    return;
  }

  if (!pieLabels.length || pieLabels.length !== pieValues.length) {
    pieChartEl.parentElement.innerHTML = emptyState(
      config.dataset.noPieTitle,
      config.dataset.noPieHint,
    );
    return;
  }

  new Chart(pieChartEl.getContext('2d'), {
    type: 'pie',
    data: {
      labels: pieLabels,
      datasets: [
        {
          data: pieValues,
          backgroundColor: [
            'rgba(239, 68, 68, 0.8)',
            'rgba(251, 191, 36, 0.8)',
            'rgba(59, 130, 246, 0.8)',
            'rgba(34, 197, 94, 0.8)',
            'rgba(139, 92, 246, 0.8)',
            'rgba(236, 72, 153, 0.8)',
            'rgba(249, 115, 22, 0.8)',
            'rgba(14, 165, 233, 0.8)',
          ],
          borderColor: isDarkMode ? '#374151' : '#ffffff',
          borderWidth: 2,
          hoverOffset: 8,
        },
      ],
    },
    options: {
      ...commonOptions,
      onClick: (_event, elements) => {
        const element = elements[0];
        if (!element) {
          return;
        }
        openFinances(config, {
          type: 'expense',
          category: [pieCategoryKeys[element.index]],
        });
      },
      plugins: {
        ...commonOptions.plugins,
        tooltip: {
          ...commonOptions.plugins.tooltip,
          callbacks: {
            label: (context) => {
              const label = context.label || '';
              const value = context.parsed || 0;
              const total = context.dataset.data.reduce((a, b) => a + b, 0);
              const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : '0.0';
              return `${label}: ${value.toLocaleString('ru-RU', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })} (${percentage}%)`;
            },
          },
        },
      },
    },
  });
});
