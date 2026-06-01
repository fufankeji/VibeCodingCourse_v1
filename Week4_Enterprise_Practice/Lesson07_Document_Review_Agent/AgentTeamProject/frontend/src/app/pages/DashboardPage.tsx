import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { Plus, FileText, Clock, CheckCircle, AlertTriangle, ArrowRight, Loader2 } from 'lucide-react';
import { GlobalNav } from '../components/GlobalNav';
import { StateBadge } from '../components/StateBadge';
import { listContracts, type ContractItem } from '../api/contracts';
import { useAuth } from '../contexts/AuthContext';
import { contractRoute, contractState, isContractNavigable } from '../utils/contracts';
import { formatApiDate, isSameLocalDay, isSameLocalMonth, parseApiDate } from '../utils/datetime';

/**
 * DashboardPage — P02 工作台首页
 * 统计数据来自当前后端方案任务列表。
 */
export function DashboardPage() {
  const navigate = useNavigate();
  const { user } = useAuth();

  const [contracts, setContracts] = useState<ContractItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    listContracts({ limit: 100 })
      .then((res) => {
        setContracts(res.items);
        setTotal(res.total);
      })
      .catch(() => {})
      .finally(() => setIsLoading(false));
  }, []);

  const pendingContracts = contracts.filter((c) =>
    c.session_state === 'hitl_pending' || c.session_state === 'hitl_high_risk' || c.session_state === 'hitl_medium_confirm'
  );
  const recentContracts = [...contracts]
    .sort((a, b) => parseApiDate(b.updated_at || b.uploaded_at || b.created_at).getTime() - parseApiDate(a.updated_at || a.uploaded_at || a.created_at).getTime())
    .slice(0, 6);
  const completedContracts = contracts.filter((c) => {
    const state = contractState(c);
    return state === 'report_ready' && isSameLocalMonth(c.updated_at || c.uploaded_at || c.created_at);
  });
  const todayContracts = contracts.filter((c) => isSameLocalDay(c.uploaded_at || c.created_at));

  const routeToContract = (contract: ContractItem) => {
    const route = contractRoute(contract);
    if (route) navigate(route);
  };

  const formatDate = (iso: string) => formatApiDate(iso, { year: undefined });

  return (
    <div className="min-h-screen bg-gray-50">
      <GlobalNav />
      <div className="pt-14">
        <div className="max-w-6xl mx-auto px-6 py-8">
          {/* Header */}
          <div className="flex items-center justify-between mb-8">
            <div>
              <h1 className="text-gray-900" style={{ fontSize: 22, fontWeight: 700 }}>
                你好，{user?.name}
              </h1>
              <p className="text-gray-500 text-sm mt-1">欢迎回到水土保持方案智能评审工作台</p>
            </div>
            <button
              onClick={() => navigate('/contracts/upload')}
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2.5 rounded-lg text-sm transition-colors"
              style={{ fontWeight: 500 }}
            >
              <Plus className="w-4 h-4" />
              新建审核
            </button>
          </div>

          {/* Stats Cards */}
          <div className="grid grid-cols-3 gap-4 mb-8">
            <StatCard
              icon={<AlertTriangle className="w-5 h-5 text-orange-500" />}
              label="待复核方案"
              value={String(pendingContracts.length)}
              note={`总任务 ${total} 个`}
              color="orange"
            />
            <StatCard
              icon={<CheckCircle className="w-5 h-5 text-green-500" />}
              label="本月已完成"
              value={String(completedContracts.length)}
              note="来自当前任务列表"
              color="green"
            />
            <StatCard
              icon={<FileText className="w-5 h-5 text-blue-500" />}
              label="今日新增"
              value={String(todayContracts.length)}
              note="按上传时间统计"
              color="blue"
            />
          </div>

          <div className="grid grid-cols-2 gap-6">
            {/* 待我处理 */}
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
              <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
                <h2 className="text-gray-800" style={{ fontWeight: 600, fontSize: 15 }}>
                  待我处理
                </h2>
                <span className="text-xs text-gray-400">待人工复核任务</span>
              </div>
              <div className="divide-y divide-gray-50">
                {isLoading ? (
                  <div className="px-5 py-8 text-center text-sm text-gray-400 flex items-center justify-center gap-2">
                    <Loader2 className="w-4 h-4 animate-spin" /> 加载中…
                  </div>
                ) : pendingContracts.length === 0 ? (
                  <div className="px-5 py-8 text-center text-sm text-gray-400">暂无待复核方案</div>
                ) : (
                  pendingContracts.map((contract) => (
                    <div key={contract.id} className="px-5 py-3.5 flex items-center justify-between hover:bg-gray-50">
                      <div>
                        <p className="text-sm text-gray-800" style={{ fontWeight: 500 }}>{contract.title}</p>
                        <div className="flex items-center gap-2 mt-1">
                          <Clock className="w-3 h-3 text-gray-400" />
                          <span className="text-xs text-gray-400">{formatDate(contract.created_at)}</span>
                        </div>
                      </div>
                      <button
                        onClick={() => routeToContract(contract)}
                        className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 hover:bg-blue-50 px-2.5 py-1.5 rounded-md transition-colors"
                        style={{ fontWeight: 500 }}
                      >
                        继续评审 <ArrowRight className="w-3 h-3" />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* 最近审核 */}
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
              <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
                <h2 className="text-gray-800" style={{ fontWeight: 600, fontSize: 15 }}>最近审核</h2>
                <button
                  onClick={() => navigate('/contracts')}
                  className="text-xs text-blue-600 hover:text-blue-800"
                >
                  查看全部
                </button>
              </div>
              <div className="divide-y divide-gray-50">
                {recentContracts.map((contract) => (
                  <button
                    key={contract.id}
                    type="button"
                    onClick={() => routeToContract(contract)}
                    disabled={!isContractNavigable(contract)}
                    className="w-full px-5 py-3 flex items-center justify-between text-left transition-colors enabled:hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    <div>
                      <p className="text-sm text-gray-800">{contract.title}</p>
                      <span className="text-xs text-gray-400">{formatDate(contract.uploaded_at || contract.created_at)}</span>
                    </div>
                    <StateBadge state={contractState(contract)} />
                  </button>
                ))}
                {!isLoading && recentContracts.length === 0 && (
                  <div className="px-5 py-8 text-center text-sm text-gray-400">暂无方案评审任务</div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({
  icon, label, value, note, color,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  note: string;
  color: 'orange' | 'green' | 'blue';
}) {
  const bg = { orange: 'bg-orange-50', green: 'bg-green-50', blue: 'bg-blue-50' }[color];
  return (
    <div className={`${bg} rounded-xl border border-gray-200 px-5 py-5`}>
      <div className="flex items-center gap-2 mb-2">{icon}<span className="text-sm text-gray-600">{label}</span></div>
      <p className="text-gray-900" style={{ fontSize: 28, fontWeight: 700, lineHeight: 1 }}>{value}</p>
      <p className="text-xs text-gray-400 mt-1">{note}</p>
    </div>
  );
}
