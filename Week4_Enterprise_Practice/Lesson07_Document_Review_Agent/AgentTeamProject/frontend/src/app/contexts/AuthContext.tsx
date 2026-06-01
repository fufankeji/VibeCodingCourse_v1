import React, { createContext, useContext, useState } from 'react';
import type { User, UserRole } from '../types';
import { apiClient } from '../api/client';

const LOCAL_USERS: User[] = [
  { id: 'user-001', name: '张三', role: 'reviewer', email: 'reviewer@local' },
  { id: 'user-002', name: '李四', role: 'submitter', email: 'submitter@local' },
  { id: 'user-003', name: '王管理', role: 'admin', email: 'admin@local' },
];

interface AuthContextValue {
  user: User | null;
  login: (role: UserRole) => void;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  login: () => {},
  logout: () => {},
  isAuthenticated: false,
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);

  const login = (role: UserRole) => {
    const found = LOCAL_USERS.find((u) => u.role === role) ?? LOCAL_USERS[0];
    setUser(found);
    apiClient.setUser(found.id, found.role);
  };

  const logout = () => setUser(null);

  return (
    <AuthContext.Provider value={{ user, login, logout, isAuthenticated: !!user }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
