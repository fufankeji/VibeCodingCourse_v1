import ReactECharts from 'echarts-for-react'
import type { ChartConfig } from '../../types'

interface ChartProps {
  config: ChartConfig
}

export function Chart({ config }: ChartProps) {
  const getOption = () => {
    const { type, title, data, xField, yField } = config

    const baseOption = {
      title: {
        text: title,
        textStyle: {
          color: '#e2e8f0',
          fontSize: 14,
        },
        left: 'center',
      },
      tooltip: {
        trigger: type === 'pie' ? 'item' : 'axis',
        backgroundColor: 'rgba(30, 41, 59, 0.9)',
        borderColor: '#475569',
        textStyle: { color: '#e2e8f0' },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        containLabel: true,
      },
    }

    switch (type) {
      case 'bar':
        return {
          ...baseOption,
          xAxis: {
            type: 'category',
            data: data.map((d) => d[xField || 'name']),
            axisLine: { lineStyle: { color: '#475569' } },
            axisLabel: { color: '#94a3b8' },
          },
          yAxis: {
            type: 'value',
            axisLine: { lineStyle: { color: '#475569' } },
            axisLabel: { color: '#94a3b8' },
            splitLine: { lineStyle: { color: '#334155' } },
          },
          series: [
            {
              type: 'bar',
              data: data.map((d) => d[yField || 'value']),
              itemStyle: {
                color: {
                  type: 'linear',
                  x: 0, y: 0, x2: 0, y2: 1,
                  colorStops: [
                    { offset: 0, color: '#3b82f6' },
                    { offset: 1, color: '#1d4ed8' },
                  ],
                },
                borderRadius: [4, 4, 0, 0],
              },
            },
          ],
        }

      case 'line':
        return {
          ...baseOption,
          xAxis: {
            type: 'category',
            data: data.map((d) => d[xField || 'name']),
            axisLine: { lineStyle: { color: '#475569' } },
            axisLabel: { color: '#94a3b8' },
          },
          yAxis: {
            type: 'value',
            axisLine: { lineStyle: { color: '#475569' } },
            axisLabel: { color: '#94a3b8' },
            splitLine: { lineStyle: { color: '#334155' } },
          },
          series: [
            {
              type: 'line',
              data: data.map((d) => d[yField || 'value']),
              smooth: true,
              lineStyle: { color: '#3b82f6', width: 2 },
              areaStyle: {
                color: {
                  type: 'linear',
                  x: 0, y: 0, x2: 0, y2: 1,
                  colorStops: [
                    { offset: 0, color: 'rgba(59, 130, 246, 0.3)' },
                    { offset: 1, color: 'rgba(59, 130, 246, 0.05)' },
                  ],
                },
              },
              itemStyle: { color: '#3b82f6' },
            },
          ],
        }

      case 'pie':
        return {
          ...baseOption,
          series: [
            {
              type: 'pie',
              radius: ['40%', '70%'],
              center: ['50%', '55%'],
              data: data.map((d) => ({
                name: d[xField || 'name'],
                value: d[yField || 'value'],
              })),
              label: {
                color: '#94a3b8',
              },
              itemStyle: {
                borderColor: '#1e293b',
                borderWidth: 2,
              },
            },
          ],
        }

      default:
        return baseOption
    }
  }

  return (
    <ReactECharts
      option={getOption()}
      style={{ height: '100%', width: '100%' }}
      theme="dark"
    />
  )
}
