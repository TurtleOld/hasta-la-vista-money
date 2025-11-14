const chartConfigs = {
    expensesTrend: {
        tooltip: {
            trigger: 'axis',
            axisPointer: {
                type: 'cross',
            },
        },
        legend: {
            data: ['Расходы', 'Тренд', 'Прогноз'],
            bottom: 0,
        },
        grid: {
            left: '3%',
            right: '4%',
            bottom: '15%',
            containLabel: true,
        },
        xAxis: {
            type: 'category',
            boundaryGap: false,
            data: [],
        },
        yAxis: {
            type: 'value',
        },
        series: [
            {
                name: 'Расходы',
                type: 'bar',
                data: [],
                itemStyle: {
                    color: '#ef4444',
                },
            },
            {
                name: 'Тренд',
                type: 'line',
                smooth: true,
                data: [],
                itemStyle: {
                    color: '#3b82f6',
                },
            },
            {
                name: 'Прогноз',
                type: 'line',
                lineStyle: {
                    type: 'dashed',
                },
                data: [],
                itemStyle: {
                    color: '#94a3b8',
                },
            },
        ],
        toolbox: {
            feature: {
                dataZoom: {
                    yAxisIndex: 'none',
                },
                restore: {},
                saveAsImage: {
                    pixelRatio: 2,
                },
            },
        },
    },

    incomeTrend: {
        tooltip: {
            trigger: 'axis',
            axisPointer: {
                type: 'cross',
            },
        },
        legend: {
            data: ['Доходы', 'Тренд', 'Прогноз'],
            bottom: 0,
        },
        grid: {
            left: '3%',
            right: '4%',
            bottom: '15%',
            containLabel: true,
        },
        xAxis: {
            type: 'category',
            boundaryGap: false,
            data: [],
        },
        yAxis: {
            type: 'value',
        },
        series: [
            {
                name: 'Доходы',
                type: 'bar',
                data: [],
                itemStyle: {
                    color: '#22c55e',
                },
            },
            {
                name: 'Тренд',
                type: 'line',
                smooth: true,
                data: [],
                itemStyle: {
                    color: '#3b82f6',
                },
            },
            {
                name: 'Прогноз',
                type: 'line',
                lineStyle: {
                    type: 'dashed',
                },
                data: [],
                itemStyle: {
                    color: '#94a3b8',
                },
            },
        ],
        toolbox: {
            feature: {
                dataZoom: {
                    yAxisIndex: 'none',
                },
                restore: {},
                saveAsImage: {
                    pixelRatio: 2,
                },
            },
        },
    },

    categoryDrillDown: {
        tooltip: {
            trigger: 'item',
            formatter: function(params) {
                const seriesName = params.seriesName || '';
                const name = params.name || '';
                const value = params.value || 0;
                const percent = params.percent || 0;
                return seriesName + '<br/>' + name + ': ' + value + ' (' + percent + '%)';
            },
        },
        legend: {
            orient: 'vertical',
            left: 'left',
            bottom: 0,
        },
        series: [
            {
                name: 'Расходы по категориям',
                type: 'pie',
                radius: ['40%', '70%'],
                avoidLabelOverlap: false,
                itemStyle: {
                    borderRadius: 10,
                    borderColor: '#fff',
                    borderWidth: 2,
                },
                label: {
                    show: false,
                    position: 'center',
                },
                emphasis: {
                    label: {
                        show: true,
                        fontSize: 18,
                        fontWeight: 'bold',
                    },
                    itemStyle: {
                        shadowBlur: 10,
                        shadowOffsetX: 0,
                        shadowColor: 'rgba(0, 0, 0, 0.5)',
                    },
                },
                labelLine: {
                    show: false,
                },
                data: [],
            },
        ],
    },

    comparison: {
        tooltip: {
            trigger: 'axis',
        },
        legend: {
            data: ['Текущий период', 'Прошлый период'],
            bottom: 0,
        },
        grid: {
            left: '3%',
            right: '4%',
            bottom: '15%',
            containLabel: true,
        },
        xAxis: {
            type: 'category',
            data: ['Расходы', 'Доходы', 'Сбережения'],
        },
        yAxis: {
            type: 'value',
        },
        series: [
            {
                name: 'Текущий период',
                type: 'bar',
                data: [],
                itemStyle: {
                    color: '#3b82f6',
                },
            },
            {
                name: 'Прошлый период',
                type: 'bar',
                data: [],
                itemStyle: {
                    color: '#94a3b8',
                },
            },
        ],
    },

    balance: {
        tooltip: {
            trigger: 'axis',
        },
        legend: {
            data: ['Баланс'],
            bottom: 0,
        },
        grid: {
            left: '3%',
            right: '4%',
            bottom: '15%',
            containLabel: true,
        },
        xAxis: {
            type: 'category',
            boundaryGap: false,
            data: [],
        },
        yAxis: {
            type: 'value',
        },
        series: [
            {
                name: 'Баланс',
                type: 'line',
                smooth: true,
                areaStyle: {
                    color: {
                        type: 'linear',
                        x: 0,
                        y: 0,
                        x2: 0,
                        y2: 1,
                        colorStops: [
                            {
                                offset: 0,
                                color: 'rgba(59, 130, 246, 0.3)',
                            },
                            {
                                offset: 1,
                                color: 'rgba(59, 130, 246, 0.1)',
                            },
                        ],
                    },
                },
                data: [],
                itemStyle: {
                    color: '#3b82f6',
                },
            },
        ],
    },
};

window.chartConfigs = chartConfigs;
