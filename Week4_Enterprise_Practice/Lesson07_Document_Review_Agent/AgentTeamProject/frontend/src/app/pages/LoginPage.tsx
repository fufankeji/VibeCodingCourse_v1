import { useState } from 'react';
import { useNavigate } from 'react-router';
import { FileText, Eye, EyeOff } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import type { UserRole } from '../types';

export function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPwd, setShowPwd] = useState(false);
  const [error, setError] = useState('');
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleQuickLogin = (role: UserRole) => {
    login(role);
    if (role === 'admin') navigate('/admin');
    else navigate('/dashboard');
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError('用户名和密码不能为空');
      return;
    }
    setError('');
    // 本地开发：用户名密码校验暂未接入后端，以 reviewer 身份进入。
    login('reviewer');
    navigate('/dashboard');
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex flex-col items-center justify-center px-4">
      {/* Logo */}
      <div className="flex flex-col items-center mb-8">
        <div className="w-14 h-14 bg-blue-600 rounded-2xl flex items-center justify-center shadow-lg mb-4">
          <FileText className="w-8 h-8 text-white" />
        </div>
        <h1 className="text-gray-900" style={{ fontSize: 24, fontWeight: 700 }}>水土保持方案智能评审</h1>
        <p className="text-gray-500 text-sm mt-1">Soil and Water Conservation Review System</p>
      </div>

      {/* Login Card */}
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-8">
        <h2 className="text-gray-800 mb-6" style={{ fontWeight: 600, fontSize: 18 }}>用户登录</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-700 mb-1">用户名</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="请输入用户名"
              className="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-700 mb-1">密码</label>
            <div className="relative">
              <input
                type={showPwd ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="请输入密码"
                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent pr-10"
              />
              <button
                type="button"
                onClick={() => setShowPwd(!showPwd)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                {showPwd ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {error && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>
          )}

          <button
            type="submit"
            className="w-full bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-lg text-sm transition-colors"
            style={{ fontWeight: 500 }}
          >
            登录
          </button>
        </form>

        {/* Local Role Login */}
        <div className="mt-6 pt-5 border-t border-gray-100">
          <p className="text-xs text-gray-400 mb-3 text-center">本地角色登录</p>
          <div className="grid grid-cols-3 gap-2">
            <button
              onClick={() => handleQuickLogin('reviewer')}
              className="flex flex-col items-center py-2.5 px-3 border border-blue-200 rounded-lg bg-blue-50 hover:bg-blue-100 transition-colors"
            >
              <span className="text-xs text-blue-600" style={{ fontWeight: 600 }}>审核员</span>
              <span className="text-xs text-gray-400 mt-0.5">张三</span>
            </button>
            <button
              onClick={() => handleQuickLogin('submitter')}
              className="flex flex-col items-center py-2.5 px-3 border border-green-200 rounded-lg bg-green-50 hover:bg-green-100 transition-colors"
            >
              <span className="text-xs text-green-600" style={{ fontWeight: 600 }}>提交员</span>
              <span className="text-xs text-gray-400 mt-0.5">李四</span>
            </button>
            <button
              onClick={() => handleQuickLogin('admin')}
              className="flex flex-col items-center py-2.5 px-3 border border-red-200 rounded-lg bg-red-50 hover:bg-red-100 transition-colors"
            >
              <span className="text-xs text-red-600" style={{ fontWeight: 600 }}>管理员</span>
              <span className="text-xs text-gray-400 mt-0.5">王管理</span>
            </button>
          </div>
        </div>
      </div>

      {/* Footer */}
      <p className="text-xs text-gray-400 mt-6">© 2026 水土保持方案智能评审</p>
    </div>
  );
}
