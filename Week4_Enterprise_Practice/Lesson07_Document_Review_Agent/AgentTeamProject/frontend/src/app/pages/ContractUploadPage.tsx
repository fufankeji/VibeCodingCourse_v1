import { useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { AlertCircle, CheckCircle, FileJson, FileText, Loader2, Upload, X } from 'lucide-react';
import { GlobalNav } from '../components/GlobalNav';

const MAX_SIZE_MB = 50;
const ALLOWED_EXTS = ['.pdf', '.docx', '.json'];
const ACCEPTED_FILE_TYPES = '.pdf,.docx,.json';

const FORMAT_LABELS = [
  { label: 'PDF', detail: '原始方案' },
  { label: 'DOCX', detail: 'Word 文档' },
  { label: 'MinerU JSON', detail: '已解析结构' },
];

function formatFileSize(bytes: number) {
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function fileKind(filename: string) {
  const ext = filename.split('.').pop()?.toLowerCase();
  if (ext === 'json') return 'MinerU JSON';
  if (ext === 'docx') return 'DOCX';
  return 'PDF';
}

/**
 * ContractUploadPage — P04 方案上传页
 * POST /contracts/upload — 已开发
 * R12: 前端格式/大小校验为辅助性，上传期间按钮均禁用
 */
export function ContractUploadPage() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [contractTitle, setContractTitle] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [serverError, setServerError] = useState('');
  const [isDragging, setIsDragging] = useState(false);

  const validateFile = (file: File): string[] => {
    const errs: string[] = [];
    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    if (!ALLOWED_EXTS.includes(ext)) {
      errs.push(`文件格式不支持，仅允许 PDF / DOCX / MinerU JSON（当前：${ext}）`);
    }
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      errs.push(`文件大小超过 ${MAX_SIZE_MB}MB 限制（当前：${formatFileSize(file.size)}）`);
    }
    return errs;
  };

  const handleFileSelect = (file: File) => {
    const errs = validateFile(file);
    setErrors(errs);
    setServerError('');
    setUploadProgress(0);
    if (errs.length > 0) {
      setSelectedFile(null);
      return;
    }
    setSelectedFile(file);
    if (!contractTitle) {
      setContractTitle(file.name.replace(/\.(pdf|docx|json)$/i, ''));
    }
  };

  const clearFile = () => {
    setSelectedFile(null);
    setErrors([]);
    setServerError('');
    setUploadProgress(0);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (isUploading) return;
    const file = e.dataTransfer.files[0];
    if (file) handleFileSelect(file);
  };

  const handleSubmit = async () => {
    const errs: string[] = [];
    if (!contractTitle.trim()) errs.push('方案名称不能为空');
    if (!selectedFile) errs.push('请选择方案文件');
    if (errs.length > 0) {
      setErrors(errs);
      return;
    }

    setErrors([]);
    setServerError('');
    setIsUploading(true);
    setUploadProgress(20);

    try {
      const { uploadContract } = await import('../api/contracts');
      setUploadProgress(50);
      const result = await uploadContract(selectedFile!, contractTitle.trim());
      setUploadProgress(100);
      await new Promise((r) => setTimeout(r, 300));
      setIsUploading(false);
      navigate(`/contracts/${result.session_id}/parsing`);
    } catch (err: any) {
      setIsUploading(false);
      setUploadProgress(0);
      setServerError(err.message || '上传失败，请检查文件后重试');
    }
  };

  const isDisabled = isUploading;
  const canSubmit = Boolean(contractTitle.trim() && selectedFile && !isUploading);

  return (
    <div className="min-h-screen bg-slate-50">
      <GlobalNav />
      <main className="pt-14">
        <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6 lg:px-8">
          <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h1 className="text-xl font-semibold text-slate-950">新建方案评审</h1>
              <p className="mt-1 text-sm text-slate-600">上传水土保持方案文件，创建解析任务。</p>
            </div>
            <button
              type="button"
              onClick={() => navigate('/contracts')}
              disabled={isDisabled}
              className="inline-flex h-11 items-center justify-center rounded-md border border-slate-300 bg-white px-4 text-sm font-medium text-slate-700 shadow-sm transition-colors hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              返回列表
            </button>
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
            <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm" aria-busy={isUploading}>
              <div className="space-y-5">
                <div>
                  <label htmlFor="contract-title" className="mb-1.5 block text-sm font-medium text-slate-700">
                    方案名称 <span className="text-red-600">*</span>
                  </label>
                  <input
                    id="contract-title"
                    type="text"
                    value={contractTitle}
                    onChange={(e) => setContractTitle(e.target.value)}
                    placeholder="请输入方案名称"
                    maxLength={200}
                    disabled={isDisabled}
                    aria-invalid={errors.some((err) => err.includes('方案名称'))}
                    className="h-11 w-full rounded-md border border-slate-300 px-3 text-base text-slate-900 outline-none transition-[border-color,box-shadow] placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 disabled:bg-slate-50 disabled:text-slate-400 md:text-sm"
                  />
                </div>

                <div>
                  <div className="mb-1.5 flex items-center justify-between gap-3">
                    <label htmlFor="contract-file" className="block text-sm font-medium text-slate-700">
                      方案文件 <span className="text-red-600">*</span>
                    </label>
                    <span className="text-xs text-slate-500">最大 {MAX_SIZE_MB}MB</span>
                  </div>

                  {!selectedFile ? (
                    <>
                      <button
                        type="button"
                        onDrop={handleDrop}
                        onDragEnter={(e) => {
                          e.preventDefault();
                          if (!isDisabled) setIsDragging(true);
                        }}
                        onDragOver={(e) => {
                          e.preventDefault();
                          if (!isDisabled) setIsDragging(true);
                        }}
                        onDragLeave={() => setIsDragging(false)}
                        onClick={() => !isDisabled && fileInputRef.current?.click()}
                        disabled={isDisabled}
                        className={`flex min-h-44 w-full cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 text-center transition-[background-color,border-color,box-shadow] focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50 ${
                          isDragging
                            ? 'border-blue-500 bg-blue-50 shadow-[0_0_0_4px_rgba(37,99,235,0.08)]'
                            : 'border-slate-300 bg-slate-50 hover:border-blue-400 hover:bg-white'
                        }`}
                        aria-describedby="contract-file-help"
                      >
                        <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-blue-100 text-blue-700">
                          <Upload className="h-5 w-5" />
                        </span>
                        <span className="text-sm font-medium text-slate-800">选择或拖入方案文件</span>
                        <span id="contract-file-help" className="mt-1 text-xs text-slate-500">
                          PDF / DOCX / MinerU JSON
                        </span>
                      </button>
                      <input
                        id="contract-file"
                        ref={fileInputRef}
                        type="file"
                        accept={ACCEPTED_FILE_TYPES}
                        className="sr-only"
                        onChange={(e) => e.target.files?.[0] && handleFileSelect(e.target.files[0])}
                        disabled={isDisabled}
                      />
                    </>
                  ) : (
                    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                      <div className="flex items-start gap-3">
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-blue-100 text-blue-700">
                          {selectedFile.name.toLowerCase().endsWith('.json') ? (
                            <FileJson className="h-5 w-5" />
                          ) : (
                            <FileText className="h-5 w-5" />
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-slate-900">{selectedFile.name}</p>
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                            <span>{fileKind(selectedFile.name)}</span>
                            <span aria-hidden="true">·</span>
                            <span>{formatFileSize(selectedFile.size)}</span>
                          </div>
                        </div>
                        {!isUploading && (
                          <button
                            type="button"
                            onClick={clearFile}
                            aria-label="移除已选择文件"
                            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-white hover:text-red-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                          >
                            <X className="h-4 w-4" />
                          </button>
                        )}
                      </div>

                      {isUploading && (
                        <div className="mt-4" aria-live="polite">
                          <div className="mb-1 flex justify-between text-xs text-slate-600">
                            <span className="inline-flex items-center gap-1.5">
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              正在上传
                            </span>
                            <span>{uploadProgress}%</span>
                          </div>
                          <div
                            className="h-2 w-full overflow-hidden rounded-full bg-slate-200"
                            role="progressbar"
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-valuenow={uploadProgress}
                          >
                            <div
                              className="h-full rounded-full bg-blue-600 transition-[width] duration-200"
                              style={{ width: `${uploadProgress}%` }}
                            />
                          </div>
                        </div>
                      )}

                      {uploadProgress === 100 && !isUploading && (
                        <div className="mt-3 flex items-center gap-1.5 text-xs font-medium text-green-700">
                          <CheckCircle className="h-3.5 w-3.5" />
                          上传完成，正在创建解析任务
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {errors.length > 0 && (
                  <div className="rounded-md border border-red-200 bg-red-50 p-3" role="alert" aria-live="assertive">
                    <div className="mb-1 flex items-center gap-2 text-sm font-medium text-red-700">
                      <AlertCircle className="h-4 w-4" />
                      无法提交
                    </div>
                    <ul className="space-y-1 pl-6 text-sm text-red-700">
                      {errors.map((err, i) => (
                        <li key={i} className="list-disc">
                          {err}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {serverError && (
                  <div className="rounded-md border border-red-200 bg-red-50 p-3" role="alert" aria-live="assertive">
                    <div className="flex items-start gap-2 text-sm text-red-700">
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                      <div className="min-w-0 flex-1">
                        <p className="font-medium">上传失败</p>
                        <p className="mt-0.5 break-words">{serverError}</p>
                      </div>
                    </div>
                    <div className="mt-3 flex gap-2">
                      <button
                        type="button"
                        onClick={handleSubmit}
                        disabled={!selectedFile || isUploading}
                        className="inline-flex h-11 items-center justify-center rounded-md bg-red-600 px-3 text-sm font-medium text-white transition-colors hover:bg-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        重试
                      </button>
                      <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        disabled={isUploading}
                        className="inline-flex h-11 items-center justify-center rounded-md border border-red-200 bg-white px-3 text-sm font-medium text-red-700 transition-colors hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        更换文件
                      </button>
                    </div>
                  </div>
                )}

                <div className="flex flex-col-reverse gap-3 border-t border-slate-100 pt-4 sm:flex-row sm:justify-end">
                  <button
                    type="button"
                    onClick={() => navigate('/contracts')}
                    disabled={isDisabled}
                    className="inline-flex h-11 items-center justify-center rounded-md border border-slate-300 bg-white px-5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={handleSubmit}
                    disabled={!canSubmit}
                    className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-blue-600 px-5 text-sm font-medium text-white transition-colors hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:bg-blue-300"
                  >
                    {isUploading && <Loader2 className="h-4 w-4 animate-spin" />}
                    {isUploading ? '正在上传' : '提交审核'}
                  </button>
                </div>
              </div>
            </section>

            <aside className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <h2 className="text-sm font-semibold text-slate-900">提交检查</h2>
              <div className="mt-4 space-y-3">
                <div className="flex items-start gap-2">
                  <CheckCircle className={`mt-0.5 h-4 w-4 ${contractTitle.trim() ? 'text-green-600' : 'text-slate-300'}`} />
                  <div>
                    <p className="text-sm font-medium text-slate-800">方案名称</p>
                    <p className="text-xs text-slate-500">{contractTitle.trim() ? '已填写' : '待填写'}</p>
                  </div>
                </div>
                <div className="flex items-start gap-2">
                  <CheckCircle className={`mt-0.5 h-4 w-4 ${selectedFile ? 'text-green-600' : 'text-slate-300'}`} />
                  <div>
                    <p className="text-sm font-medium text-slate-800">方案文件</p>
                    <p className="text-xs text-slate-500">{selectedFile ? `${fileKind(selectedFile.name)} · ${formatFileSize(selectedFile.size)}` : '待选择'}</p>
                  </div>
                </div>
              </div>

              <div className="mt-5 border-t border-slate-100 pt-4">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">支持格式</p>
                <div className="mt-2 space-y-2">
                  {FORMAT_LABELS.map((item) => (
                    <div key={item.label} className="flex items-center justify-between rounded-md border border-slate-200 px-2.5 py-2">
                      <span className="text-sm font-medium text-slate-800">{item.label}</span>
                      <span className="text-xs text-slate-500">{item.detail}</span>
                    </div>
                  ))}
                </div>
              </div>
            </aside>
          </div>
        </div>
      </main>
    </div>
  );
}
