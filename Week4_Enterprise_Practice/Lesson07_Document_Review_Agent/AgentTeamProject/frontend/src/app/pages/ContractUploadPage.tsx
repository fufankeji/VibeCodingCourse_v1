import { useState, useRef } from 'react';
import { useNavigate } from 'react-router';
import { Upload, X, FileText, AlertCircle, CheckCircle } from 'lucide-react';
import { GlobalNav } from '../components/GlobalNav';

const MAX_SIZE_MB = 50;
const ALLOWED_EXTS = ['.pdf', '.doc', '.docx', '.json'];

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
      errs.push(`文件格式不支持，仅允许 PDF / Word / MinerU JSON（当前：${ext}）`);
    }
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      errs.push(`文件大小超过 ${MAX_SIZE_MB}MB 限制（当前：${(file.size / 1024 / 1024).toFixed(1)}MB）`);
    }
    return errs;
  };

  const handleFileSelect = (file: File) => {
    const errs = validateFile(file);
    setErrors(errs);
    if (errs.length === 0) {
      setSelectedFile(file);
      if (!contractTitle) {
        setContractTitle(file.name.replace(/\.(pdf|doc|docx|json)$/i, ''));
      }
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFileSelect(file);
  };

  const handleSubmit = async () => {
    const errs: string[] = [];
    if (!contractTitle.trim()) errs.push('方案名称不能为空');
    if (!selectedFile) errs.push('请选择方案文件');
    if (errs.length > 0) { setErrors(errs); return; }

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
      setServerError(err.message || '上传失败，请重试');
    }
  };

  const isDisabled = isUploading;

  return (
    <div className="min-h-screen bg-gray-50">
      <GlobalNav />
      <div className="pt-14">
        <div className="max-w-2xl mx-auto px-6 py-8">
          <div className="mb-6">
            <h1 className="text-gray-900" style={{ fontSize: 20, fontWeight: 700 }}>新建方案评审</h1>
            <p className="text-sm text-gray-500 mt-1">上传水土保持方案文件，启动智能评审流程</p>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-5">
            {/* Contract Title */}
            <div>
              <label className="block text-sm text-gray-700 mb-1.5" style={{ fontWeight: 500 }}>
                方案名称 <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={contractTitle}
                onChange={(e) => setContractTitle(e.target.value)}
                placeholder="请输入方案名称（最多 200 字符）"
                maxLength={200}
                disabled={isDisabled}
                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50 disabled:text-gray-400"
              />
            </div>

            {/* File Upload Zone */}
            <div>
              <label className="block text-sm text-gray-700 mb-1.5" style={{ fontWeight: 500 }}>
                方案文件 <span className="text-red-500">*</span>
              </label>

              {!selectedFile ? (
                <div
                  onDrop={handleDrop}
                  onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                  onDragLeave={() => setIsDragging(false)}
                  onClick={() => !isDisabled && fileInputRef.current?.click()}
                  className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors ${
                    isDragging ? 'border-blue-400 bg-blue-50' : 'border-gray-200 hover:border-blue-300 hover:bg-gray-50'
                  } ${isDisabled ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  <Upload className="w-10 h-10 text-gray-300 mx-auto mb-3" />
                  <p className="text-sm text-gray-600" style={{ fontWeight: 500 }}>拖拽文件至此或点击上传</p>
                  <p className="text-xs text-gray-400 mt-1.5">支持格式：PDF / Word / MinerU JSON · 最大 50MB</p>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.doc,.docx,.json"
                    className="hidden"
                    onChange={(e) => e.target.files?.[0] && handleFileSelect(e.target.files[0])}
                    disabled={isDisabled}
                  />
                </div>
              ) : (
                <div className="border border-gray-200 rounded-xl p-4">
                  {/* Selected File Preview */}
                  <div className="flex items-center gap-3 mb-3">
                    <div className="w-10 h-10 bg-blue-50 rounded-lg flex items-center justify-center shrink-0">
                      <FileText className="w-5 h-5 text-blue-500" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-800 truncate" style={{ fontWeight: 500 }}>{selectedFile.name}</p>
                      <p className="text-xs text-gray-400">{(selectedFile.size / 1024 / 1024).toFixed(2)} MB</p>
                    </div>
                    {!isUploading && (
                      <button
                        onClick={() => { setSelectedFile(null); setErrors([]); setUploadProgress(0); }}
                        className="text-gray-400 hover:text-red-500 transition-colors"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    )}
                  </div>

                  {/* Upload Progress Bar */}
                  {isUploading && (
                    <div>
                      <div className="flex justify-between text-xs text-gray-500 mb-1">
                        <span>正在上传…</span>
                        <span>{uploadProgress}%</span>
                      </div>
                      <div className="w-full bg-gray-100 rounded-full h-1.5">
                        <div
                          className="bg-blue-500 h-1.5 rounded-full transition-all duration-200"
                          style={{ width: `${uploadProgress}%` }}
                        />
                      </div>
                    </div>
                  )}
                  {uploadProgress === 100 && !isUploading && (
                    <div className="flex items-center gap-1.5 text-xs text-green-600">
                      <CheckCircle className="w-3.5 h-3.5" />
                      上传完成，正在创建审核任务…
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Validation Error Area */}
            {errors.length > 0 && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-3 space-y-1">
                {errors.map((err, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm text-red-600">
                    <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                    {err}
                  </div>
                ))}
              </div>
            )}
            {serverError && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-600">
                <span className="text-xs text-red-400 mr-1">[后端错误]</span>{serverError}
              </div>
            )}

            {/* Action Bar */}
            <div className="flex gap-3 pt-2">
              <button
                onClick={handleSubmit}
                disabled={isDisabled}
                className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 disabled:cursor-not-allowed text-white py-2.5 rounded-lg text-sm transition-colors"
                style={{ fontWeight: 500 }}
              >
                {isUploading ? '正在上传…' : '提交审核'}
              </button>
              <button
                onClick={() => navigate('/contracts')}
                disabled={isDisabled}
                className="px-6 py-2.5 border border-gray-300 text-gray-600 rounded-lg text-sm hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                取消
              </button>
            </div>
          </div>

          {/* API Info */}
          <div className="mt-4 p-3 bg-blue-50 border border-blue-100 rounded-lg">
            <p className="text-xs text-blue-600">
              <span style={{ fontWeight: 600 }}>API：</span>
              POST /contracts/upload (multipart/form-data) · 文件大小上限 50MB · 格式：PDF/Word/MinerU JSON
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
