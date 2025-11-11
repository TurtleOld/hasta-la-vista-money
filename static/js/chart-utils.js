/* global echarts */

function initChart(containerId, config) {
    const container = document.getElementById(containerId);
    if (!container) {
        console.error(`Container ${containerId} not found`);
        return null;
    }

    const chart = echarts.init(container, null, {renderer: 'canvas'});
    chart.setOption(config);

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

