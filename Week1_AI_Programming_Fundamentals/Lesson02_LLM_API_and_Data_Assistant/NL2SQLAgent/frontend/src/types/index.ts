// 会话类型 - 匹配后端 snake_case
export interface Session {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

// 消息类型 - 匹配后端
export interface Message {
  id: number | string
  session_id?: string
  role: 'user' | 'assistant' | 'system'
  content: string
  sql_query?: string
  created_at?: string
}

// 图表配置类型
export interface ChartConfig {
  type: 'bar' | 'line' | 'pie' | 'scatter' | 'table'
  title: string
  data: Array<{ name: string; value: number | string }>
  xField?: string
  yField?: string
  seriesField?: string
}

// 表格数据类型
export interface TableData {
  columns: string[]
  rows: Array<{ name: string; value: number | string }>
  raw?: Array<Array<string | number>>
}

// SSE 事件类型
export type SSEEventType = 'thinking' | 'text' | 'sql' | 'data' | 'chart' | 'error' | 'done'

// SSE 数据响应
export interface SSEDataResponse {
  columns: string[]
  rows: Array<{ name: string; value: number | string }>
  raw: Array<Array<string | number>>
}

// 聊天请求
export interface ChatRequest {
  session_id: string
  message: string
}

// 视图模式
export type ViewMode = 'chart' | 'table'
