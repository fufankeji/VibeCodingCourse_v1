import type { HealthStatus, Model, Conversation, ChatRequest, StreamChunk } from '../types'

const API_BASE = '/api'

export async function checkHealth(): Promise<HealthStatus> {
  try {
    const response = await fetch(`${API_BASE}/health`)
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
    const data = await response.json()
    return {
      status: 'healthy',
      timestamp: data.timestamp,
      version: data.version,
      service: data.service,
    }
  } catch (error) {
    return {
      status: 'unhealthy',
      error: error instanceof Error ? error.message : 'Unknown error',
    }
  }
}

export async function getModels(): Promise<Model[]> {
  try {
    const response = await fetch(`${API_BASE}/models`)
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
    const data = await response.json()
    return data.models
  } catch (error) {
    console.error('Failed to fetch models:', error)
    return []
  }
}

// Conversation APIs
export async function fetchConversations(): Promise<Conversation[]> {
  try {
    const response = await fetch(`${API_BASE}/conversations`)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return await response.json()
  } catch (error) {
    console.error('Failed to fetch conversations:', error)
    return []
  }
}

export async function createConversation(thinkingEnabled: boolean = false): Promise<Conversation | null> {
  try {
    const response = await fetch(`${API_BASE}/conversations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ thinking_enabled: thinkingEnabled }),
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return await response.json()
  } catch (error) {
    console.error('Failed to create conversation:', error)
    return null
  }
}

export async function fetchConversation(id: string): Promise<Conversation | null> {
  try {
    const response = await fetch(`${API_BASE}/conversations/${id}`)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return await response.json()
  } catch (error) {
    console.error('Failed to fetch conversation:', error)
    return null
  }
}

export async function deleteConversation(id: string): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/conversations/${id}`, {
      method: 'DELETE',
    })
    return response.ok
  } catch (error) {
    console.error('Failed to delete conversation:', error)
    return false
  }
}

// Chat API with SSE streaming and AbortController support
export async function streamChat(
  request: ChatRequest,
  onReasoning: (chunk: string) => void,
  onContent: (chunk: string) => void,
  onDone: (reasoning: string | null, content: string) => void,
  onError: (error: string) => void,
  abortSignal?: AbortSignal
): Promise<void> {
  try {
    const response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal: abortSignal,
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('No reader available')

    const decoder = new TextDecoder()
    let buffer = ''
    let fullReasoning = ''
    let fullContent = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const chunk: StreamChunk = JSON.parse(line.slice(6))
              
              if (chunk.type === 'reasoning' && chunk.data) {
                fullReasoning += chunk.data
                onReasoning(chunk.data)
              } else if (chunk.type === 'content' && chunk.data) {
                fullContent += chunk.data
                onContent(chunk.data)
              } else if (chunk.type === 'done') {
                onDone(chunk.reasoning || fullReasoning || null, chunk.content || fullContent)
                return
              } else if (chunk.type === 'error') {
                onError(chunk.error || 'Unknown error')
                return
              }
            } catch {
              // Ignore parse errors
            }
          }
        }
      }
      // Stream ended without done signal
      onDone(fullReasoning || null, fullContent)
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        // Request was aborted, call onDone with current content
        onDone(fullReasoning || null, fullContent)
        return
      }
      throw error
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      // Silently handle abort
      return
    }
    onError(error instanceof Error ? error.message : 'Unknown error')
  }
}
