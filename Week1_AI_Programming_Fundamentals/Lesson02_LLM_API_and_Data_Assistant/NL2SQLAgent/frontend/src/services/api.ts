/**
 * API 服务层 - 封装所有后端接口调用
 */

const API_BASE = 'http://localhost:8000/api'

// 通用请求封装
async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  })
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || 'Request failed')
  }
  
  return response.json()
}

// Session 相关类型
export interface Session {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface Message {
  id: number | string
  session_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  sql_query?: string
  created_at: string
}

export interface SessionWithMessages extends Session {
  messages: Message[]
}

// Database 相关类型
export interface TableInfo {
  name: string
  columns: string[]
  sample_data?: string
}

export interface DatabaseSchema {
  tables: TableInfo[]
}

/**
 * Session API
 */
export const sessionApi = {
  // 获取所有会话列表
  list: (): Promise<Session[]> => {
    return request<Session[]>('/sessions')
  },
  
  // 创建新会话
  create: (title?: string): Promise<Session> => {
    return request<Session>('/sessions', {
      method: 'POST',
      body: JSON.stringify({ title: title || '新会话' }),
    })
  },
  
  // 获取单个会话（包含消息）
  get: (id: string): Promise<SessionWithMessages> => {
    return request<SessionWithMessages>(`/sessions/${id}`)
  },
  
  // 更新会话
  update: (id: string, data: { title?: string }): Promise<Session> => {
    return request<Session>(`/sessions/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },
  
  // 删除会话
  delete: (id: string): Promise<void> => {
    return request<void>(`/sessions/${id}`, {
      method: 'DELETE',
    })
  },
  
  // 获取会话消息列表
  getMessages: (id: string): Promise<Message[]> => {
    return request<Message[]>(`/sessions/${id}/messages`)
  },
}

/**
 * Database API
 */
export const databaseApi = {
  // 获取数据库 Schema
  getSchema: (): Promise<DatabaseSchema> => {
    return request<DatabaseSchema>('/database/schema')
  },
  
  // 获取表列表
  getTables: (): Promise<string[]> => {
    return request<string[]>('/database/tables')
  },
}

/**
 * Chat API - SSE 流式聊天
 */
export interface ChatRequest {
  session_id: string
  message: string
}

export interface SSEEventData {
  event: 'thinking' | 'text' | 'sql' | 'data' | 'chart' | 'error' | 'done'
  data: string | object
}

export interface SSEDataPayload {
  columns: string[]
  rows: Array<{ name: string; value: number | string }>
  raw: Array<Array<string | number>>
}

export interface SSEChartPayload {
  type: 'bar' | 'line' | 'pie' | 'scatter' | 'table'
  title: string
  data: Array<{ name: string; value: number | string }>
  xField?: string
  yField?: string
  seriesField?: string
}

/**
 * 创建 SSE 聊天连接
 * 
 * @param request 聊天请求
 * @returns SSE 处理器
 */
export function createChatSSE(request: ChatRequest) {
  const controller = new AbortController()
  
  return {
    /**
     * 开始 SSE 流式请求
     */
    start: async (handlers: {
      onThinking?: (text: string) => void
      onText?: (text: string) => void
      onSql?: (sql: string) => void
      onData?: (data: SSEDataPayload) => void
      onChart?: (config: SSEChartPayload) => void
      onError?: (error: string) => void
      onDone?: () => void
    }) => {
      try {
        const response = await fetch(`${API_BASE}/chat`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream',
          },
          body: JSON.stringify(request),
          signal: controller.signal,
        })
        
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`)
        }
        
        const reader = response.body?.getReader()
        if (!reader) {
          throw new Error('No response body')
        }
        
        const decoder = new TextDecoder()
        let buffer = ''
        
        while (true) {
          const { done, value } = await reader.read()
          
          if (done) {
            handlers.onDone?.()
            break
          }
          
          buffer += decoder.decode(value, { stream: true })
          
          // 按行解析 SSE 事件
          const lines = buffer.split('\n')
          buffer = lines.pop() || '' // 保留不完整的行
          
          let currentEvent = ''
          const dataLines: string[] = []
          
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              // 如果有待处理的事件，先处理它
              if (currentEvent && dataLines.length > 0) {
                processEvent(currentEvent, dataLines.join('\n'), handlers)
              }
              currentEvent = line.slice(7).trim()
              dataLines.length = 0
            } else if (line.startsWith('data: ')) {
              // 累积多行数据
              dataLines.push(line.slice(6))
            } else if (line === '' && currentEvent && dataLines.length > 0) {
              // 空行表示事件结束
              processEvent(currentEvent, dataLines.join('\n'), handlers)
              currentEvent = ''
              dataLines.length = 0
            }
          }
        }
      } catch (error) {
        if ((error as Error).name !== 'AbortError') {
          handlers.onError?.((error as Error).message)
        }
      }
    },
    
    /**
     * 中止 SSE 请求
     */
    abort: () => {
      controller.abort()
    },
  }
}

/**
 * 处理单个 SSE 事件
 */
function processEvent(
  event: string,
  data: string,
  handlers: {
    onThinking?: (text: string) => void
    onText?: (text: string) => void
    onSql?: (sql: string) => void
    onData?: (data: SSEDataPayload) => void
    onChart?: (config: SSEChartPayload) => void
    onError?: (error: string) => void
    onDone?: () => void
  }
) {
  try {
    switch (event) {
      case 'thinking':
        handlers.onThinking?.(data)
        break
        
      case 'text':
        handlers.onText?.(data)
        break
        
      case 'sql':
        handlers.onSql?.(data)
        break
        
      case 'data':
        const dataPayload = JSON.parse(data) as SSEDataPayload
        handlers.onData?.(dataPayload)
        break
        
      case 'chart':
        const chartPayload = JSON.parse(data) as SSEChartPayload
        handlers.onChart?.(chartPayload)
        break
        
      case 'error':
        handlers.onError?.(data)
        break
        
      case 'done':
        handlers.onDone?.()
        break
        
      default:
        console.warn('Unknown SSE event:', event)
    }
  } catch (e) {
    console.error('Error processing SSE event:', e, { event, data })
  }
}

// 导出统一的 API 对象
export const api = {
  session: sessionApi,
  database: databaseApi,
  chat: createChatSSE,
}

export default api
