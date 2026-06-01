import type { ReviewDocumentContentResponse, ReviewDocumentPage } from '../../api/sessions';
import { pdfFrameUrl } from '../document';
import type { ViewerMode } from '../types';
import { ParsedEvidenceView } from './ParsedEvidenceView';

interface DocumentViewerProps {
  content: ReviewDocumentContentResponse | null;
  activePage: ReviewDocumentPage | null;
  activePageNumber: number;
  viewerMode: ViewerMode;
  onViewerModeChange: (mode: ViewerMode) => void;
}

export function DocumentViewer({
  content,
  activePage,
  activePageNumber,
  viewerMode,
  onViewerModeChange,
}: DocumentViewerProps) {
  if (!content) {
    return (
      <section className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">
        暂无可查看的解析文档。
      </section>
    );
  }

  const hasPdf = Boolean(content.source_pdf_url);
  const activeViewerMode: ViewerMode = hasPdf ? viewerMode : 'parsed';
  const pdfUrl = pdfFrameUrl(content.source_pdf_url, activePageNumber);

  return (
    <section className="min-w-0 rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-950">
            第 {activePage?.page_number ?? activePageNumber} 页
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            {activeViewerMode === 'pdf'
              ? '浏览器原生渲染原始 PDF；证据定位请切换到解析视图。'
              : '按 MinerU 解析块顺序展示文本、表格和图片引用。'}
          </p>
        </div>
        {hasPdf ? (
          <div className="flex rounded border border-slate-200 bg-slate-50 p-0.5 text-xs">
            <button
              type="button"
              onClick={() => onViewerModeChange('pdf')}
              className={`rounded px-2 py-1 ${
                activeViewerMode === 'pdf' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-white'
              }`}
            >
              原始PDF
            </button>
            <button
              type="button"
              onClick={() => onViewerModeChange('parsed')}
              className={`rounded px-2 py-1 ${
                activeViewerMode === 'parsed' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-white'
              }`}
            >
              解析证据
            </button>
          </div>
        ) : null}
      </div>
      {activeViewerMode === 'pdf' && pdfUrl ? (
        <iframe
          key={pdfUrl}
          title={`${content.title} 原始PDF`}
          src={pdfUrl}
          className="h-[calc(100vh-230px)] min-h-[760px] w-full border-0 bg-white"
        />
      ) : (
        <ParsedEvidenceView page={activePage} />
      )}
    </section>
  );
}
