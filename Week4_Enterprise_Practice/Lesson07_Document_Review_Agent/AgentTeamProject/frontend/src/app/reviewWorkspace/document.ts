import { API_BASE_URL } from '../api/client';
import type { ReviewDocumentContentResponse, ReviewDocumentPage } from '../api/sessions';

export function countDocumentBlocks(content: ReviewDocumentContentResponse | null): number {
  return content?.pages.reduce((total, page) => total + page.blocks.length, 0) ?? 0;
}

export function firstPageNumber(content: ReviewDocumentContentResponse | null): number {
  return content?.pages[0]?.page_number ?? 1;
}

export function findPage(content: ReviewDocumentContentResponse | null, pageNumber: number): ReviewDocumentPage | null {
  return content?.pages.find((page) => page.page_number === pageNumber) ?? content?.pages[0] ?? null;
}

export function resolveSessionFileUrl(path?: string): string {
  const value = path?.trim();
  if (!value) return '';
  if (/^https?:\/\//i.test(value)) return value;
  try {
    return new URL(value, API_BASE_URL).toString();
  } catch {
    return value;
  }
}

export function pdfFrameUrl(path: string | undefined, page: number): string {
  const url = resolveSessionFileUrl(path);
  if (!url) return '';
  const [base] = url.split('#');
  return `${base}#page=${Math.max(1, page)}&zoom=page-width`;
}
