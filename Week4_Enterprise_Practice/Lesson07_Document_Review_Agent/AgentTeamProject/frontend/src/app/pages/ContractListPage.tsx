import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { Plus, Search, Filter, ChevronRight, AlertTriangle, Loader2 } from 'lucide-react';
import { GlobalNav } from '../components/GlobalNav';
import { StateBadge } from '../components/StateBadge';
import { listContracts, type ContractItem } from '../api/contracts';
import type { SessionState } from '../types';
import { contractRoute, contractState, isContractNavigable } from '../utils/contracts';
import { formatApiDate } from '../utils/datetime';

const STATE_OPTIONS: { value: '' | SessionState; label: string }[] = [
  { value: '', label: '全部状态' },
  { value: 'parsing', label: '解析中' },
  { value: 'scanning', label: '规则审查中' },
  { value: 'hitl_field_verify', label: '字段核对' },
  { value: 'hitl_pending', label: '待人工审核' },
  { value: 'hitl_medium_confirm', label: '中风险复核' },
  { value: 'report_ready', label: '已完成' },
  { value: 'aborted', label: '已中止' },
];

/**
 * ContractListPage — P03 方案列表页
 * GET /contracts — 已开发（游标分页，state 筛选）
 * GET /contracts?keyword=xxx — 「未开发」：api_spec 未定义 keyword 参数
 */
export function ContractListPage() {
  const navigate = useNavigate();
  const [stateFilter, setStateFilter] = useState<'' | SessionState>('');
  const [keyword, setKeyword] = useState('');
  const [contracts, setContracts] = useState<ContractItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  const fetchContracts = async (cursor?: string) => {
    const isMore = !!cursor;
    if (isMore) setIsLoadingMore(true); else setIsLoading(true);
    try {
      const res = await listContracts({
        cursor: cursor || undefined,
        limit: 20,
        state: stateFilter || undefined,
      });
      if (isMore) {
        setContracts((prev) => [...prev, ...res.items]);
      } else {
        setContracts(res.items);
      }
      setNextCursor(res.next_cursor);
      setTotal(res.total);
      setLoadError('');
    } catch (err: any) {
      setLoadError(err.message || '加载方案列表失败');
    } finally {
      setIsLoading(false);
      setIsLoadingMore(false);
    }
  };

  useEffect(() => {
    fetchContracts();
  }, [stateFilter]);

  // Local keyword filter (backend doesn't support keyword search)
  const filtered = keyword
    ? contracts.filter((c) => c.title.includes(keyword) || c.original_filename.includes(keyword))
    : contracts;

  const handleRowClick = (contract: ContractItem) => {
    const route = contractRoute(contract);
    if (route) navigate(route);
  };

  const formatDate = (iso: string) => formatApiDate(iso);

  return (
    <div className="min-h-screen bg-gray-50">
      <GlobalNav />
      <div className="pt-14">
        <div className="max-w-6xl mx-auto px-6 py-6">
          {/* Page Header */}
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-gray-900" style={{ fontSize: 20, fontWeight: 700 }}>方案列表</h1>
              <p className="text-sm text-gray-500 mt-0.5">管理和查看所有水土保持方案评审任务</p>
            </div>
            <button
              onClick={() => navigate('/contracts/upload')}
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm transition-colors"
              style={{ fontWeight: 500 }}
            >
              <Plus className="w-4 h-4" />
              新建审核
            </button>
          </div>

          {/* Filter Bar */}
          <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 mb-4 flex items-center gap-3 flex-wrap">
            <Filter className="w-4 h-4 text-gray-400 shrink-0" />

            {/* Keyword Search */}
            <div className="relative flex-1 min-w-48">
              <Search className="w-4 h-4 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="搜索方案名称…"
                className="pl-8 pr-3 py-1.5 border border-gray-200 rounded-md text-sm w-full focus:outline-none focus:ring-1 focus:ring-blue-400"
              />
              <span
                className="absolute -top-2 right-1 bg-yellow-100 text-yellow-700 text-xs px-1 rounded border border-yellow-300"
                title="GET /contracts?keyword 参数 api_spec 未定义，当前为前端本地过滤"
              >
                未开发
              </span>
            </div>

            {/* State Filter */}
            <select
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value as '' | SessionState)}
              className="px-3 py-1.5 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
            >
              {STATE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          {/* Loading */}
          {isLoading && (
            <div className="flex items-center justify-center py-16 text-gray-400">
              <Loader2 className="w-6 h-6 animate-spin mr-2" /> 正在加载…
            </div>
          )}

          {/* Error */}
          {loadError && (
            <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 mb-4 text-sm text-red-600">
              {loadError}
            </div>
          )}

          {/* Contract List */}
          {!isLoading && (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
              <div className="grid grid-cols-12 px-5 py-2.5 bg-gray-50 border-b border-gray-100 text-xs text-gray-500">
                <div className="col-span-5">方案名称</div>
                <div className="col-span-2">上传人</div>
                <div className="col-span-2">上传时间</div>
                <div className="col-span-2">状态</div>
                <div className="col-span-1">操作</div>
              </div>

              {filtered.length === 0 ? (
                <div className="py-16 text-center text-sm text-gray-400">暂无符合条件的方案任务</div>
              ) : (
                <div className="divide-y divide-gray-50">
                  {filtered.map((contract) => (
                    <div
                      key={contract.id}
                      className={`grid grid-cols-12 px-5 py-3.5 items-center transition-colors ${
                        isContractNavigable(contract)
                          ? 'cursor-pointer hover:bg-blue-50/30'
                          : 'cursor-not-allowed bg-slate-50/60 opacity-75'
                      }`}
                      onClick={() => handleRowClick(contract)}
                    >
                      <div className="col-span-5 flex items-start gap-2">
                        <div>
                          <p className="text-sm text-gray-800" style={{ fontWeight: 500 }}>{contract.title}</p>
                          <p className="text-xs text-gray-400 mt-0.5">{contract.original_filename}</p>
                        </div>
                      </div>
                      <div className="col-span-2 text-sm text-gray-600">{contract.uploaded_by}</div>
                      <div className="col-span-2 text-xs text-gray-500">{formatDate(contract.uploaded_at || contract.created_at)}</div>
                      <div className="col-span-2 flex flex-col gap-1">
                        <StateBadge state={contractState(contract)} />
                      </div>
                      <div className="col-span-1 flex justify-end">
                        {isContractNavigable(contract) ? (
                          <ChevronRight className="w-4 h-4 text-gray-400" />
                        ) : (
                          <span className="text-xs text-gray-400">不可进入</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Pagination */}
              <div className="px-5 py-3 border-t border-gray-100 flex items-center justify-between">
                <span className="text-xs text-gray-400">共 {total} 条</span>
                {nextCursor && (
                  <button
                    onClick={() => fetchContracts(nextCursor)}
                    disabled={isLoadingMore}
                    className="text-xs text-blue-600 border border-blue-200 px-3 py-1 rounded hover:bg-blue-50 disabled:opacity-50"
                  >
                    {isLoadingMore ? '加载中…' : '加载更多'}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
