import type { ReviewDocumentContentResponse } from '../../api/sessions';
import { countDocumentBlocks } from '../document';
import { modeTitle } from '../mode';
import type { ReviewWorkspaceMode } from '../types';

interface DocumentNavigatorProps {
  mode: ReviewWorkspaceMode;
  content: ReviewDocumentContentResponse | null;
  activePageNumber: number;
  onPageChange: (page: number) => void;
}

export function DocumentNavigator({ mode, content, activePageNumber, onPageChange }: DocumentNavigatorProps) {
  return (
    <aside className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm lg:sticky lg:top-[130px] lg:max-h-[calc(100vh-150px)] lg:overflow-auto">
      <div className="mb-3">
        <p className="text-xs text-slate-500">当前环节</p>
        <h2 className="text-sm font-semibold text-slate-950">{modeTitle(mode)}</h2>
        <p className="mt-2 text-xs text-slate-500">
          页数：{content?.page_count ?? '-'} · 解析块：{countDocumentBlocks(content) || '-'}
        </p>
      </div>
      <div className="grid grid-cols-3 gap-2 lg:grid-cols-1">
        {(content?.pages ?? []).map((page) => (
          <button
            key={page.page_number}
            type="button"
            onClick={() => onPageChange(page.page_number)}
            className={`rounded-md border px-3 py-2 text-left text-sm transition-colors ${
              page.page_number === activePageNumber
                ? 'border-blue-300 bg-blue-50 text-blue-700'
                : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
            }`}
          >
            第 {page.page_number} 页
            <span className="ml-1 text-xs text-slate-400">{page.blocks.length} 块</span>
          </button>
        ))}
      </div>
      {content?.outline?.length ? (
        <div className="mt-4 border-t border-slate-100 pt-3">
          <p className="mb-2 text-xs text-slate-500">目录</p>
          <div className="space-y-1">
            {content.outline.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => onPageChange(item.page_number)}
                className="block w-full rounded px-2 py-1 text-left text-xs text-slate-600 hover:bg-slate-50"
                style={{ paddingLeft: `${Math.max(0, item.level - 1) * 12 + 8}px` }}
              >
                <span className="line-clamp-2">{item.title}</span>
                <span className="text-slate-400">第 {item.page_number} 页</span>
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </aside>
  );
}
