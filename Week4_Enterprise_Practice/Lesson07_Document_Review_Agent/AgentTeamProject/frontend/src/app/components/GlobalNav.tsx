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
    <nav className="fixed top-0 left-0 right-0 z-50 h-14 bg-white border-b border-gray-200 flex items-center px-3 sm:px-6 shadow-sm">
      {/* Logo + Product Name */}
      <button
        type="button"
        className="mr-2 flex h-11 min-w-0 items-center gap-2 rounded-md pr-2 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 sm:mr-8"
        onClick={() => navigate('/dashboard')}
        aria-label="返回工作台"
      >
        <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
          <FileText className="w-4 h-4 text-white" />
        </div>
        <span className="hidden whitespace-nowrap text-gray-900 select-none sm:inline" style={{ fontWeight: 600 }}>
          水土保持方案智能评审
        </span>
      </button>

      {/* Nav Links */}
      <div className="flex min-w-0 flex-1 items-center gap-1">
        {navItems.map(({ path, label, icon: Icon }) => {
          const isActive = location.pathname === path || location.pathname.startsWith(path + '/');
          return (
            <button
              key={path}
              onClick={() => navigate(path)}
              aria-label={label}
              className={`flex h-11 w-11 shrink-0 items-center justify-center gap-1.5 rounded-md text-sm transition-colors sm:w-auto sm:px-3 ${
                isActive
                  ? 'bg-blue-50 text-blue-700'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
              }`}
            >
              <Icon className="w-4 h-4" />
              <span className="hidden whitespace-nowrap sm:inline">{label}</span>
            </button>
          );
        })}
      </div>

      {/* User Info */}
      {user && (
        <div className="flex shrink-0 items-center gap-2 sm:gap-3">
          <div className="hidden items-center gap-2 md:flex">
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
            aria-label="退出登录"
            className="flex h-11 w-11 items-center justify-center gap-1 rounded-md text-sm text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700 sm:w-auto sm:px-2"
          >
            <LogOut className="w-4 h-4" />
            <span className="hidden sm:inline">退出</span>
          </button>
        </div>
      )}
    </nav>
  );
}
