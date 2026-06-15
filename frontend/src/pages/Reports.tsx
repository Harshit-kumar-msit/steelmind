// src/pages/Reports.tsx
import { useState }      from 'react';
import { useMutation }   from '@tanstack/react-query';
import { BarChart3, Download, RefreshCw, FileText } from 'lucide-react';
import { reportsApi }    from '../api/client';

export default function Reports() {
  const [report, setReport] = useState<string>('');
  const [meta, setMeta]     = useState<Record<string, unknown>>({});

  const { mutate: generate, isPending } = useMutation({
    mutationFn: reportsApi.weekly,
    onSuccess: (data) => {
      setReport(data.content);
      setMeta(data.metadata);
    },
  });

  const downloadReport = () => {
    const blob = new Blob([report], { type: 'text/plain' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `steelmind-weekly-report-${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Management Reports</h1>
          <p className="text-sm text-gray-400 mt-0.5">LLM-generated maintenance summaries</p>
        </div>
        <div className="flex gap-2">
          {report && (
            <button
              onClick={downloadReport}
              className="flex items-center gap-2 px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm text-gray-300 transition-colors"
            >
              <Download size={14} /> Download
            </button>
          )}
          <button
            onClick={() => generate()}
            disabled={isPending}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-60 rounded-lg text-sm text-white transition-colors"
          >
            {isPending ? <RefreshCw size={14} className="animate-spin" /> : <BarChart3 size={14} />}
            {isPending ? 'Generating…' : 'Generate Weekly Report'}
          </button>
        </div>
      </div>

      {!report && !isPending && (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="w-14 h-14 rounded-2xl bg-blue-600/10 border border-blue-500/20 flex items-center justify-center mb-4">
            <FileText size={24} className="text-blue-400" />
          </div>
          <h2 className="text-base font-semibold text-white mb-2">No report generated yet</h2>
          <p className="text-sm text-gray-400 max-w-sm">
            Click "Generate Weekly Report" to create an LLM-written maintenance summary
            based on current plant data.
          </p>
        </div>
      )}

      {isPending && (
        <div className="flex items-center justify-center py-16 text-gray-400">
          <RefreshCw size={20} className="animate-spin mr-3" />
          Llama 3.3 70B is writing your report…
        </div>
      )}

      {report && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-white">Weekly Maintenance Summary</h2>
            <span className="text-xs text-gray-500">Generated {new Date().toLocaleString()}</span>
          </div>
          <div className="prose prose-invert prose-sm max-w-none">
            <pre className="whitespace-pre-wrap text-sm text-gray-300 leading-relaxed font-sans">
              {report}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
