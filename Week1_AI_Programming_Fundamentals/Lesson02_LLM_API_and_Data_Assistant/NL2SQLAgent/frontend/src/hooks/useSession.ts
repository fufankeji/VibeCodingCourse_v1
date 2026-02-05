/**
 * 会话管理 Hook - 处理会话的加载、创建、删除等操作
 */
import { useCallback, useEffect, useState } from 'react'
import { useAppStore } from '../store/useAppStore'
import { sessionApi, type Session, type Message } from '../services/api'

export function useSession() {
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  
  const {
    sessions,
    currentSessionId,
    setSessions,
    addSession,
    selectSession,
    deleteSession: removeSession,
    setMessages,
    clearMessages,
  } = useAppStore()

  /**
   * 加载会话列表
   */
  const loadSessions = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    
    try {
      const data = await sessionApi.list()
      setSessions(data)
      
      // 如果有会话但没有选中的，选中第一个
      if (data.length > 0 && !currentSessionId) {
        selectSession(data[0].id)
      }
    } catch (e) {
      setError((e as Error).message)
      console.error('Failed to load sessions:', e)
    } finally {
      setIsLoading(false)
    }
  }, [setSessions, selectSession, currentSessionId])

  /**
   * 创建新会话
   */
  const createSession = useCallback(async (title?: string): Promise<Session | null> => {
    setIsLoading(true)
    setError(null)
    
    try {
      const newSession = await sessionApi.create(title)
      addSession(newSession)
      selectSession(newSession.id)
      clearMessages()
      return newSession
    } catch (e) {
      setError((e as Error).message)
      console.error('Failed to create session:', e)
      
      // 回退到本地创建
      const localSession = useAppStore.getState().createSession()
      return localSession
    } finally {
      setIsLoading(false)
    }
  }, [addSession, selectSession, clearMessages])

  /**
   * 选择会话并加载消息
   */
  const selectAndLoadSession = useCallback(async (sessionId: string) => {
    selectSession(sessionId)
    setIsLoading(true)
    setError(null)
    
    try {
      const messages = await sessionApi.getMessages(sessionId)
      setMessages(messages as Message[])
    } catch (e) {
      setError((e as Error).message)
      console.error('Failed to load messages:', e)
      // 不影响选择，只是没有历史消息
      setMessages([])
    } finally {
      setIsLoading(false)
    }
  }, [selectSession, setMessages])

  /**
   * 删除会话
   */
  const deleteSession = useCallback(async (sessionId: string) => {
    setIsLoading(true)
    setError(null)
    
    try {
      await sessionApi.delete(sessionId)
      removeSession(sessionId)
    } catch (e) {
      setError((e as Error).message)
      console.error('Failed to delete session:', e)
      // 即使 API 失败，也从本地删除
      removeSession(sessionId)
    } finally {
      setIsLoading(false)
    }
  }, [removeSession])

  /**
   * 更新会话标题
   */
  const updateSessionTitle = useCallback(async (sessionId: string, title: string) => {
    try {
      await sessionApi.update(sessionId, { title })
      useAppStore.getState().updateSessionTitle(sessionId, title)
    } catch (e) {
      console.error('Failed to update session title:', e)
      // 本地更新
      useAppStore.getState().updateSessionTitle(sessionId, title)
    }
  }, [])

  // 初始化时加载会话列表
  useEffect(() => {
    loadSessions()
  }, []) // 只在组件挂载时加载一次

  return {
    sessions,
    currentSessionId,
    isLoading,
    error,
    loadSessions,
    createSession,
    selectSession: selectAndLoadSession,
    deleteSession,
    updateSessionTitle,
  }
}
