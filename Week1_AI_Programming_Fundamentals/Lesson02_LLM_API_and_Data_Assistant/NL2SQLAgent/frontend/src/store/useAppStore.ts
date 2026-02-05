import { create } from 'zustand'
import type { Session, Message, ChartConfig, TableData, ViewMode } from '../types'

// 生成唯一 ID
const generateId = () => Math.random().toString(36).substring(2, 15)

// 获取当前时间
const now = () => new Date().toISOString()

interface AppState {
  // 会话状态
  sessions: Session[]
  currentSessionId: string | null
  
  // 消息状态
  messages: Message[]
  isStreaming: boolean
  currentSql: string | null
  
  // 图表状态
  chartConfig: ChartConfig | null
  tableData: TableData | null
  viewMode: ViewMode
  
  // 会话操作
  setSessions: (sessions: Session[]) => void
  addSession: (session: Session) => void
  createSession: () => Session
  selectSession: (id: string) => void
  deleteSession: (id: string) => void
  updateSessionTitle: (id: string, title: string) => void
  
  // 消息操作
  setMessages: (messages: Message[]) => void
  addMessage: (message: Omit<Message, 'id' | 'created_at'>) => void
  addMessageFromServer: (message: Message) => void
  updateLastMessage: (content: string) => void
  updateLastMessageSql: (sql: string) => void
  clearMessages: () => void
  setStreaming: (streaming: boolean) => void
  setCurrentSql: (sql: string | null) => void
  
  // 图表操作
  setChartConfig: (config: ChartConfig | null) => void
  setTableData: (data: TableData | null) => void
  setViewMode: (mode: ViewMode) => void
  clearChartData: () => void
}

export const useAppStore = create<AppState>((set, get) => ({
  // 初始状态
  sessions: [],
  currentSessionId: null,
  messages: [],
  isStreaming: false,
  currentSql: null,
  chartConfig: null,
  tableData: null,
  viewMode: 'chart',
  
  // 会话操作
  setSessions: (sessions: Session[]) => {
    set({ sessions })
  },
  
  addSession: (session: Session) => {
    set((state) => ({
      sessions: [session, ...state.sessions],
    }))
  },
  
  createSession: () => {
    const newSession: Session = {
      id: generateId(),
      title: '新会话',
      created_at: now(),
      updated_at: now(),
      message_count: 0,
    }
    set((state) => ({
      sessions: [newSession, ...state.sessions],
      currentSessionId: newSession.id,
      messages: [],
      chartConfig: null,
      tableData: null,
      currentSql: null,
    }))
    return newSession
  },
  
  selectSession: (id: string) => {
    set({
      currentSessionId: id,
      messages: [],
      chartConfig: null,
      tableData: null,
      currentSql: null,
    })
  },
  
  deleteSession: (id: string) => {
    set((state) => {
      const newSessions = state.sessions.filter((s) => s.id !== id)
      const newCurrentId = state.currentSessionId === id
        ? (newSessions[0]?.id ?? null)
        : state.currentSessionId
      return {
        sessions: newSessions,
        currentSessionId: newCurrentId,
        messages: state.currentSessionId === id ? [] : state.messages,
      }
    })
  },
  
  updateSessionTitle: (id: string, title: string) => {
    set((state) => ({
      sessions: state.sessions.map((s) =>
        s.id === id ? { ...s, title, updated_at: now() } : s
      ),
    }))
  },
  
  // 消息操作
  setMessages: (messages: Message[]) => {
    set({ messages })
  },
  
  addMessage: (message) => {
    const newMessage: Message = {
      ...message,
      id: generateId(),
      created_at: now(),
    }
    set((state) => ({
      messages: [...state.messages, newMessage],
    }))
    
    // 更新会话标题（如果是第一条用户消息）
    const { currentSessionId, messages } = get()
    if (
      message.role === 'user' &&
      messages.length === 0 &&
      currentSessionId
    ) {
      const title = message.content.slice(0, 30) + (message.content.length > 30 ? '...' : '')
      set((state) => ({
        sessions: state.sessions.map((s) =>
          s.id === currentSessionId ? { ...s, title, updated_at: now() } : s
        ),
      }))
    }
  },
  
  addMessageFromServer: (message: Message) => {
    set((state) => ({
      messages: [...state.messages, message],
    }))
  },
  
  updateLastMessage: (content: string) => {
    set((state) => {
      const messages = [...state.messages]
      if (messages.length > 0) {
        messages[messages.length - 1] = {
          ...messages[messages.length - 1],
          content,
        }
      }
      return { messages }
    })
  },
  
  updateLastMessageSql: (sql: string) => {
    set((state) => {
      const messages = [...state.messages]
      if (messages.length > 0) {
        messages[messages.length - 1] = {
          ...messages[messages.length - 1],
          sql_query: sql,
        }
      }
      return { messages, currentSql: sql }
    })
  },
  
  clearMessages: () => {
    set({ messages: [], chartConfig: null, tableData: null, currentSql: null })
  },
  
  setStreaming: (streaming: boolean) => {
    set({ isStreaming: streaming })
  },
  
  setCurrentSql: (sql: string | null) => {
    set({ currentSql: sql })
  },
  
  // 图表操作
  setChartConfig: (config) => {
    set({ chartConfig: config })
  },
  
  setTableData: (data) => {
    set({ tableData: data })
  },
  
  setViewMode: (mode) => {
    set({ viewMode: mode })
  },
  
  clearChartData: () => {
    set({ chartConfig: null, tableData: null })
  },
}))
