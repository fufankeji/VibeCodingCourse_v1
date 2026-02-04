import { create } from 'zustand'
import type { ChatState, Message, Conversation } from '../types'
import { fetchConversations, createConversation, fetchConversation, deleteConversation as apiDeleteConversation } from '../services/api'

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).substr(2)
}

interface ChatStore extends ChatState {
  // Abort controller
  abortController: AbortController | null
  
  // Actions
  setSidebarOpen: (open: boolean) => void
  setThinkingEnabled: (enabled: boolean) => void
  
  // Conversation actions
  loadConversations: () => Promise<void>
  createNewConversation: () => Promise<string | null>
  switchConversation: (id: string) => Promise<void>
  deleteConversation: (id: string) => Promise<void>
  updateConversationInList: (conversation: Conversation) => void
  
  // Message actions
  addUserMessage: (content: string) => string
  startAssistantMessage: () => string
  appendReasoning: (chunk: string) => void
  appendContent: (chunk: string) => void
  finishStreaming: (reasoning: string | null, content: string) => void
  setStreaming: (streaming: boolean) => void
  
  // Abort
  setAbortController: (controller: AbortController | null) => void
  abortStreaming: () => void
  
  // Clear
  clearCurrentChat: () => void
}

export const useChatStore = create<ChatStore>((set, get) => ({
  // Initial state
  conversations: [],
  currentConversationId: null,
  messages: [],
  thinkingEnabled: false,
  isStreaming: false,
  streamingMessageId: null,
  streamingReasoning: '',
  streamingContent: '',
  sidebarOpen: true,
  abortController: null,

  // UI actions
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  
  setThinkingEnabled: (enabled) => set({ thinkingEnabled: enabled }),

  // Abort controller
  setAbortController: (controller) => set({ abortController: controller }),
  
  abortStreaming: () => {
    const { abortController } = get()
    if (abortController) {
      abortController.abort()
      set({ 
        abortController: null,
        isStreaming: false,
      })
    }
  },

  // Conversation actions
  loadConversations: async () => {
    const conversations = await fetchConversations()
    set({ conversations })
  },

  createNewConversation: async () => {
    const state = get()
    const conversation = await createConversation(state.thinkingEnabled)
    if (conversation) {
      set((state) => ({
        conversations: [conversation, ...state.conversations],
        currentConversationId: conversation.id,
        messages: [],
      }))
      return conversation.id
    }
    return null
  },

  switchConversation: async (id) => {
    const conversation = await fetchConversation(id)
    if (conversation) {
      // Map messages to correct format
      const messages: Message[] = (conversation.messages || []).map(m => ({
        id: m.id || generateId(),
        role: m.role as 'user' | 'assistant',
        content: m.content,
        reasoning_content: m.reasoning_content,
        createdAt: m.createdAt || new Date().toISOString(),
      }))
      
      set({
        currentConversationId: id,
        messages,
        thinkingEnabled: conversation.thinking_enabled === 'true',
      })
    }
  },

  deleteConversation: async (id) => {
    const success = await apiDeleteConversation(id)
    if (success) {
      set((state) => {
        const newConversations = state.conversations.filter((c) => c.id !== id)
        const isCurrentDeleted = state.currentConversationId === id
        
        return {
          conversations: newConversations,
          currentConversationId: isCurrentDeleted ? null : state.currentConversationId,
          messages: isCurrentDeleted ? [] : state.messages,
        }
      })
    }
  },

  updateConversationInList: (conversation) => {
    set((state) => ({
      conversations: state.conversations.map((c) => 
        c.id === conversation.id ? conversation : c
      ),
    }))
  },

  // Message actions
  addUserMessage: (content) => {
    const messageId = generateId()
    
    const newMessage: Message = {
      id: messageId,
      role: 'user',
      content,
      createdAt: new Date().toISOString(),
    }
    
    set((state) => ({
      messages: [...state.messages, newMessage],
    }))
    
    return messageId
  },

  startAssistantMessage: () => {
    const messageId = generateId()
    const state = get()
    
    const newMessage: Message = {
      id: messageId,
      role: 'assistant',
      content: '',
      reasoning_content: state.thinkingEnabled ? '' : undefined,
      createdAt: new Date().toISOString(),
    }
    
    set({
      messages: [...state.messages, newMessage],
      isStreaming: true,
      streamingMessageId: messageId,
      streamingReasoning: '',
      streamingContent: '',
    })
    
    return messageId
  },

  appendReasoning: (chunk) => {
    set((state) => {
      const newReasoning = state.streamingReasoning + chunk
      const updatedMessages = state.messages.map((m) => {
        if (m.id === state.streamingMessageId) {
          return { ...m, reasoning_content: newReasoning }
        }
        return m
      })
      
      return {
        streamingReasoning: newReasoning,
        messages: updatedMessages,
      }
    })
  },

  appendContent: (chunk) => {
    set((state) => {
      const newContent = state.streamingContent + chunk
      const updatedMessages = state.messages.map((m) => {
        if (m.id === state.streamingMessageId) {
          return { ...m, content: newContent }
        }
        return m
      })
      
      return {
        streamingContent: newContent,
        messages: updatedMessages,
      }
    })
  },

  finishStreaming: (reasoning, content) => {
    set((state) => {
      // 更新最终消息
      const updatedMessages = state.messages.map((m) => {
        if (m.id === state.streamingMessageId) {
          return { 
            ...m, 
            content: content || m.content,
            reasoning_content: reasoning !== null ? reasoning : m.reasoning_content,
          }
        }
        return m
      })
      
      return {
        isStreaming: false,
        streamingMessageId: null,
        streamingReasoning: '',
        streamingContent: '',
        messages: updatedMessages,
        abortController: null,
      }
    })
  },

  setStreaming: (streaming) => set({ isStreaming: streaming }),

  clearCurrentChat: () => {
    set({
      currentConversationId: null,
      messages: [],
    })
  },
}))
