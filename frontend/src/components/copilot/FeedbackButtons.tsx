// src/components/copilot/FeedbackButtons.tsx
// Gap 2: Feedback loop UI
// Thumbs up/down on each assistant message.
// On thumbs-down: shows optional correction textarea.
// Submits to POST /copilot/feedback

import { useState } from 'react';
import { ThumbsUp, ThumbsDown, CheckCircle, X } from 'lucide-react';
import clsx from 'clsx';
import { feedbackApi } from '../../api/client';
import { useAuthStore } from '../../store';
import toast from 'react-hot-toast';

interface FeedbackButtonsProps {
  sessionId:      string;
  messageIndex:   number;
  equipmentId:    string;
  userQuery:      string;   // the question that prompted this response
  aiResponse:     string;   // the assistant's answer
  intent:         string;
}

export default function FeedbackButtons({
  sessionId, messageIndex, equipmentId, userQuery, aiResponse, intent
}: FeedbackButtonsProps) {
  const { user } = useAuthStore();
  const [submitted, setSubmitted]         = useState(false);
  const [rating, setRating]               = useState<number | null>(null);
  const [showCorrection, setShowCorrection] = useState(false);
  const [correction, setCorrection]       = useState('');
  const [submitting, setSubmitting]       = useState(false);

  const submit = async (r: number, correctionText = '') => {
    if (submitted || submitting) return;
    setSubmitting(true);
    try {
      await feedbackApi.submit({
        session_id:      sessionId,
        message_index:   messageIndex,
        equipment_id:    equipmentId,
        user_id:         user?.user_id ?? 'unknown',
        user_query:      userQuery,
        ai_response:     aiResponse.slice(0, 1000), // cap to avoid huge payloads
        rating:          r,
        correction_text: correctionText,
        intent,
      });
      setRating(r);
      setSubmitted(true);
      setShowCorrection(false);
      if (r > 0) toast.success('Thanks for the feedback!');
      else       toast.success('Feedback recorded — this helps improve future responses');
    } catch {
      toast.error('Could not submit feedback');
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <div className="flex items-center gap-1.5 mt-2">
        <CheckCircle size={12} className="text-green-400" />
        <span className="text-[10px] text-gray-500">
          {rating === 1 ? 'Marked as helpful' : 'Feedback recorded'}
        </span>
      </div>
    );
  }

  return (
    <div className="mt-2 space-y-1">
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-gray-600">Was this helpful?</span>
        <button
          onClick={() => submit(1)}
          disabled={submitting}
          aria-label="Mark response as helpful"
          className="p-1 rounded hover:bg-green-500/10 text-gray-500 hover:text-green-400 transition-colors"
        >
          <ThumbsUp size={12} />
        </button>
        <button
          onClick={() => { setShowCorrection(true); }}
          disabled={submitting}
          aria-label="Mark response as unhelpful"
          className="p-1 rounded hover:bg-red-500/10 text-gray-500 hover:text-red-400 transition-colors"
        >
          <ThumbsDown size={12} />
        </button>
      </div>

      {/* Correction form - shown on thumbs down */}
      {showCorrection && (
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-300 font-medium">What was wrong? (optional)</span>
            <button onClick={() => submit(-1, '')} className="text-gray-500 hover:text-gray-300">
              <X size={12} />
            </button>
          </div>
          <textarea
            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 placeholder-gray-500 resize-none focus:outline-none focus:border-blue-500"
            rows={2}
            placeholder="e.g. The vibration limit cited was wrong — ISO 10816-3 says 4.5 for zone C, not 4.0"
            value={correction}
            onChange={e => setCorrection(e.target.value)}
          />
          <div className="flex gap-2">
            <button
              onClick={() => submit(-1, correction)}
              disabled={submitting}
              className="text-xs px-2.5 py-1 bg-red-600/20 hover:bg-red-600/30 text-red-400 border border-red-500/30 rounded transition-colors"
            >
              {submitting ? 'Submitting…' : 'Submit feedback'}
            </button>
            <button
              onClick={() => submit(-1, '')}
              className="text-xs px-2.5 py-1 text-gray-400 hover:text-white transition-colors"
            >
              Skip correction
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
