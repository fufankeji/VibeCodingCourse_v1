import { FileText, Image as ImageIcon } from 'lucide-react';
import type { ReviewDocumentBlock, ReviewDocumentPage } from '../../api/sessions';

function blockLabel(type: string) {
  if (type === 'title') return '标题';
  if (type === 'table') return '表格';
  if (type === 'image') return '图片';
  return '正文';
}

export function ParsedEvidenceView({ page }: { page: ReviewDocumentPage | null }) {
  if (!page) {
    return <div className="p-4 text-sm text-slate-500">暂无可展示的解析块。</div>;
  }

  return (
    <div className="space-y-3 p-4">
      {page.blocks.map((block, index) => (
        <ParsedBlockCard key={block.block_id || `${page.page_number}-${index}`} block={block} />
      ))}
    </div>
  );
}

function ParsedBlockCard({ block }: { block: ReviewDocumentBlock }) {
  const hasImage = Boolean(block.image_path);

  return (
    <article className="rounded-md border border-slate-100 bg-slate-50 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-0.5">
          {hasImage ? <ImageIcon className="h-3.5 w-3.5" /> : <FileText className="h-3.5 w-3.5" />}
          {blockLabel(block.type)}
        </span>
        <span className="break-all">{block.block_id}</span>
        {block.section_hint ? <span>{block.section_hint}</span> : null}
      </div>
      {block.text ? <p className="whitespace-pre-wrap text-sm leading-7 text-slate-800">{block.text}</p> : null}
      {block.html ? (
        <pre className="mt-2 max-h-56 overflow-auto rounded-md bg-white p-3 text-xs leading-5 text-slate-600">
          {block.html}
        </pre>
      ) : null}
      {hasImage ? (
        <div className="mt-3">
          {block.image_path?.startsWith('/api/') || block.image_path?.startsWith('http') ? (
            <img
              src={block.image_path}
              alt={block.text || block.block_id}
              className="max-h-[520px] max-w-full rounded-md border border-slate-200 bg-white object-contain"
            />
          ) : null}
          <p className="mt-1 break-all text-xs text-slate-500">{block.image_path}</p>
        </div>
      ) : null}
      {block.bbox?.length ? <p className="mt-2 text-xs text-slate-400">bbox: {block.bbox.join(', ')}</p> : null}
    </article>
  );
}
