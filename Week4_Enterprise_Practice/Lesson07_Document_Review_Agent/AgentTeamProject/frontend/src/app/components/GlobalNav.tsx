import { useNavigate, useLocation } from 'react-router';
import { FileText, LayoutDashboard, Settings, LogOut, User as UserIcon } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

const ROLE_LABEL: Record<string, string> = {
  reviewer: '审核员',
  submitter: '提交员',
  admin: '管理员',
};

const ROLE_COLOR: Record<string, string> = {
  reviewer: 'bg-blue-100 text-blue-700',
  submitter: 'bg-green-100 text-green-700',
  admin: 'bg-red-100 text-red-700',
};

export function GlobalNav() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const navItems = [
    { path: '/dashboard', label: '工作台', icon: LayoutDashboard },
    { path: '/contracts', label: '方案列表', icon: FileText },
    ...(user?.role === 'admin' ? [{ path: '/admin', label: '系统管理', icon: Settings }] : []),
  ];

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 h-14 bg-white border-b border-gray-200 flex items-center px-6 shadow-sm">
      {/* Logo + Product Name */}
      <div className="flex items-center gap-2 mr-8 cursor-pointer" onClick={() => navigate('/dashboard')}>
        <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
          <FileText className="w-4 h-4 text-white" />
        </div>
        <span className="text-gray-900 select-none" style={{ fontWeight: 600, letterSpacing: '-0.01em' }}>
          水土保持方案智能评审
        </span>
      </div>

      {/* Nav Links */}
      <div className="flex items-center gap-1 flex-1">
        {navItems.map(({ path, label, icon: Icon }) => {
          const isActive = location.pathname === path || location.pathname.startsWith(path + '/');
          return (
            <button
              key={path}
              onClick={() => navigate(path)}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-md text-sm transition-colors ${
                isActive
                  ? 'bg-blue-50 text-blue-700'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
              }`}
            >
              <Icon className="w-4 h-4" />
              {label}
            </button>
          );
        })}
      </div>

      {/* User Info */}
      {user && (
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-gray-200 rounded-full flex items-center justify-center">
              <UserIcon className="w-4 h-4 text-gray-600" />
            </div>
            <div className="text-sm">
              <span className="text-gray-800">{user.name}</span>
              <span className={`ml-2 text-xs px-1.5 py-0.5 rounded ${ROLE_COLOR[user.role]}`}>
                {ROLE_LABEL[user.role]}
              </span>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 hover:bg-gray-100 px-2 py-1.5 rounded-md transition-colors"
          >
            <LogOut className="w-4 h-4" />
            退出
          </button>
        </div>
      )}
    </nav>
  );
}
