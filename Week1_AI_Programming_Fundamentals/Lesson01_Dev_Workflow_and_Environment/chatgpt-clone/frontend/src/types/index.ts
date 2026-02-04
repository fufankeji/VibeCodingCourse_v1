export type ModelType = 'deepseek-chat' | 'deepseek-chat-thinking'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning_content?: string | null
  createdAt: string
}

export interface Conversation {
  id: string
  title: string
  model: string
  thinking_enabled: string
  createdAt: string
  updatedAt: string
  messages?: Message[]
}

export interface HealthStatus {
  status: 'healthy' | 'unhealthy' | 'checking'
  timestamp?: string
  version?: string
  service?: string
  error?: string
}

export interface Model {
  id: ModelType
  name: string
  description: string
  type: 'chat' | 'reasoning'
  thinking_enabled: boolean
}

export interface ChatState {
  // Conversations
  conversations: Conversation[]
  currentConversationId: string | null
  
  // Current chat
  messages: Message[]
  thinkingEnabled: boolean
  
  // Streaming state
  isStreaming: boolean
  streamingMessageId: string | null
  streamingReasoning: string
  streamingContent: string
  
  // UI state
  sidebarOpen: boolean
}

export interface StreamChunk {
  type: 'reasoning' | 'content' | 'done' | 'error'
  data?: string
  reasoning?: string | null
  content?: string
  error?: string
}

export interface ChatRequest {
  messages: { role: string; content: string }[]
  conversation_id?: string | null
  thinking_enabled: boolean
}
