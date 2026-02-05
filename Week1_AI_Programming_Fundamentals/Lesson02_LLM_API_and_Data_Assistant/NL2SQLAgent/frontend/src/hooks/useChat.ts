/**
 * 聊天 Hook - 处理 SSE 流式聊天逻辑
 */
import { useCallback, useRef } from 'react'
import { useAppStore } from '../store/useAppStore'
import { api, sessionApi, type SSEDataPayload, type SSEChartPayload } from '../services/api'
import type { ChartConfig, TableData } from '../types'

export function useChat() {
  const abortRef = useRef<(() => void) | null>(null)
  
  const {
    currentSessionId,
    isStreaming,
    addMessage,
    updateLastMessage,
    updateLastMessageSql,
    setStreaming,
    setChartConfig,
    setTableData,
    setCurrentSql,
    clearChartData,
  } = useAppStore()

  /**
   * 发送消息并处理 SSE 响应
   */
  const sendMessage = useCallback(async (content: string) => {
    // 获取或创建会话
    let sessionId = currentSessionId
    
    if (!sessionId) {
      // 创建新会话
      try {
        const newSession = await sessionApi.create(content.slice(0, 30))
        useAppStore.getState().addSession(newSession)
        useAppStore.getState().selectSession(newSession.id)
        sessionId = newSession.id
      } catch (error) {
        console.error('Failed to create session:', error)
        // 回退到本地会话
        const localSession = useAppStore.getState().createSession()
        sessionId = localSession.id
      }
    }
    
    // 清空图表数据
    clearChartData()
    setCurrentSql(null)
    
    // 添加用户消息
    addMessage({ role: 'user', content })
    
    // 开始流式响应
    setStreaming(true)
    
    // 添加 AI 消息占位
    addMessage({ role: 'assistant', content: '' })
    
    // 用于累积文本内容
    let fullText = ''
    
    // 创建 SSE 连接
    const sse = api.chat({
      session_id: sessionId!,
      message: content,
    })
    
    // 保存 abort 函数
    abortRef.current = sse.abort
    
    // 开始处理 SSE 事件
    await sse.start({
      onThinking: (text) => {
        // 显示思考过程（可选：添加到消息中或单独显示）
        console.log('Thinking:', text)
      },
      
      onText: (text) => {
        fullText += text
        updateLastMessage(fullText)
      },
      
      onSql: (sql) => {
        updateLastMessageSql(sql)
        setCurrentSql(sql)
      },
      
      onData: (data: SSEDataPayload) => {
        // 转换为表格数据格式
        const tableData: TableData = {
          columns: data.columns,
          rows: data.rows,
          raw: data.raw,
        }
        setTableData(tableData)
      },
      
      onChart: (config: SSEChartPayload) => {
        // 转换为图表配置格式
        const chartConfig: ChartConfig = {
          type: config.type,
          title: config.title,
          data: config.data,
          xField: config.xField,
          yField: config.yField,
          seriesField: config.seriesField,
        }
        setChartConfig(chartConfig)
      },
      
      onError: (error) => {
        fullText += `\n\n**错误:** ${error}`
        updateLastMessage(fullText)
      },
      
      onDone: () => {
        setStreaming(false)
        abortRef.current = null
      },
    })
  }, [
    currentSessionId,
    addMessage,
    updateLastMessage,
    updateLastMessageSql,
    setStreaming,
    setChartConfig,
    setTableData,
    setCurrentSql,
    clearChartData,
  ])

  /**
   * 中止当前请求
   */
  const abort = useCallback(() => {
    if (abortRef.current) {
      abortRef.current()
      abortRef.current = null
      setStreaming(false)
    }
  }, [setStreaming])

  return {
    sendMessage,
    abort,
    isStreaming,
  }
}
