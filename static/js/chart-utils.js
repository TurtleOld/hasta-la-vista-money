/* global echarts */

function initChart(containerId, config) {
    const container = document.getElementById(containerId);
    if (!container) {
        console.error(`Container ${containerId} not found`);
        return null;
    }

    const isDarkMode = document.documentElement.classList.contains('dark') ||
                      document.body.getAttribute('data-bs-theme') === 'dark';

    const textColor = isDarkMode ? '#ffffff' : '#333333';
    const gridColor = isDarkMode ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';

    const enhancedConfig = JSON.parse(JSON.stringify(config));

    if (enhancedConfig.xAxis) {
        if (Array.isArray(enhancedConfig.xAxis)) {
            enhancedConfig.xAxis.forEach(axis => {
                if (axis.axisLabel) {
                    axis.axisLabel.color = textColor;
                } else {
                    axis.axisLabel = { color: textColor };
                }
            });
        } else {
            if (enhancedConfig.xAxis.axisLabel) {
                enhancedConfig.xAxis.axisLabel.color = textColor;
            } else {
                enhancedConfig.xAxis.axisLabel = { color: textColor };
            }
        }
    }

    if (enhancedConfig.yAxis) {
        if (Array.isArray(enhancedConfig.yAxis)) {
            enhancedConfig.yAxis.forEach(axis => {
                if (axis.axisLabel) {
                    axis.axisLabel.color = textColor;
                } else {
                    axis.axisLabel = { color: textColor };
                }
            });
        } else {
            if (enhancedConfig.yAxis.axisLabel) {
                enhancedConfig.yAxis.axisLabel.color = textColor;
            } else {
                enhancedConfig.yAxis.axisLabel = { color: textColor };
            }
        }
    }

    if (enhancedConfig.legend) {
        if (enhancedConfig.legend.textStyle) {
            enhancedConfig.legend.textStyle.color = textColor;
        } else {
            enhancedConfig.legend.textStyle = { color: textColor };
        }
    }

    if (enhancedConfig.tooltip) {
        if (!enhancedConfig.tooltip.backgroundColor) {
            enhancedConfig.tooltip.backgroundColor = isDarkMode ? 'rgba(31, 41, 55, 0.95)' : 'rgba(255, 255, 255, 0.95)';
        }
        if (!enhancedConfig.tooltip.textStyle) {
            enhancedConfig.tooltip.textStyle = { color: textColor };
        } else {
            enhancedConfig.tooltip.textStyle.color = textColor;
        }
    }

    if (enhancedConfig.grid && Array.isArray(enhancedConfig.grid)) {
        enhancedConfig.grid.forEach(grid => {
            if (!grid.borderColor) {
                grid.borderColor = gridColor;
            }
        });
    } else if (enhancedConfig.grid && !enhancedConfig.grid.borderColor) {
        enhancedConfig.grid.borderColor = gridColor;
    }

    const chart = echarts.init(container, null, {renderer: 'canvas'});
    chart.setOption(enhancedConfig);

    window.addEventListener('resize', () => {
        chart.resize();
    });

    return chart;
}

function updateChartData(chart, newData) {
    if (!chart) {
        return;
    }

    chart.setOption({
        series: [{data: newData}],
    });
}

function updateChartOption(chart, option) {
    if (!chart) {
        return;
    }

    chart.setOption(option);
}

function addDrillDownHandler(chart, callback) {
    if (!chart) {
        return;
    }

    chart.off('click');
    chart.on('click', callback);
}

function exportChartImage(chart, filename = 'chart.png') {
    if (!chart) {
        return;
    }

    const url = chart.getDataURL({
        type: 'png',
        pixelRatio: 2,
        backgroundColor: '#fff',
    });

    const link = document.createElement('a');
    link.download = filename;
    link.href = url;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function destroyChart(chart) {
    if (chart) {
        chart.dispose();
    }
}

window.initChart = initChart;
window.updateChartOption = updateChartOption;
window.updateChartData = updateChartData;
window.addDrillDownHandler = addDrillDownHandler;
window.exportChartImage = exportChartImage;
window.destroyChart = destroyChart;
