import { AlertCircle, BookOpen, Sliders, Users } from 'lucide-react';
import { GlobalNav } from '../components/GlobalNav';

const ADMIN_MODULES = [
  {
    title: '用户与角色',
    icon: <Users className="w-4 h-4" />,
    description: '后续接入组织用户、角色授权与操作审计。',
  },
  {
    title: '水保规则库',
    icon: <BookOpen className="w-4 h-4" />,
    description: '后续提供规则版本、适用地区、适用项目类型和启停管理。',
  },
  {
    title: '评审阈值',
    icon: <Sliders className="w-4 h-4" />,
    description: '后续配置召回阈值、风险定级策略和人工复核触发条件。',
  },
];

/**
 * AdminPage — P11 系统管理页
 * 管理 API 尚未实现，页面不展示虚拟用户或虚拟规则数据。
 */
export function AdminPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <GlobalNav />
      <div className="pt-14">
        <div className="max-w-5xl mx-auto px-6 py-6">
          <div className="mb-6">
            <h1 className="text-gray-900" style={{ fontSize: 20, fontWeight: 700 }}>系统管理</h1>
            <p className="text-sm text-gray-500 mt-1">当前版本聚焦水土保持方案评审主链路，管理后台等待后端 API 接入。</p>
          </div>

          <div className="bg-blue-50 border border-blue-200 rounded-xl px-5 py-4 mb-6 flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-blue-600 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm text-blue-800" style={{ fontWeight: 700 }}>未接入管理数据</p>
              <p className="text-xs text-blue-700 mt-1">
                已移除用户、规则、阈值等页面内置展示数据。后续接入真实管理接口后再开放编辑能力。
              </p>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            {ADMIN_MODULES.map((module) => (
              <div key={module.title} className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
                <div className="w-9 h-9 rounded-lg bg-gray-100 flex items-center justify-center text-gray-600 mb-4">
                  {module.icon}
                </div>
                <h2 className="text-gray-800 text-sm" style={{ fontWeight: 600 }}>{module.title}</h2>
                <p className="text-xs text-gray-500 mt-2 leading-relaxed">{module.description}</p>
                <div className="mt-4 text-xs text-gray-400 border-t border-gray-100 pt-3">等待真实 API 接入</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
