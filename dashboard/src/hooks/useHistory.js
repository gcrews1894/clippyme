import { useState, useEffect } from 'react';
import { HISTORY_KEY, HISTORY_MAX_ITEMS } from '../lib/constants';

/**
 * Manages the ClippyMe job history list persisted to localStorage.
 *
 * @returns {{
 *   history: Array<object>,
 *   setHistory: (next: Array<object>) => void,
 *   saveToHistory: (entry: object) => void,
 *   deleteFromHistory: (jobId: string) => void,
 *   clearHistory: () => void,
 * }}
 */
export function useHistory() {
  const [history, setHistory] = useState([]);

  // Load on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem(HISTORY_KEY);
      if (saved) setHistory(JSON.parse(saved));
    } catch {
      /* ignore */
    }
  }, []);

  const saveToHistory = (entry) => {
    setHistory((prev) => {
      const updated = [entry, ...prev.filter((h) => h.jobId !== entry.jobId)].slice(
        0,
        HISTORY_MAX_ITEMS,
      );
      try {
        localStorage.setItem(HISTORY_KEY, JSON.stringify(updated));
      } catch {
        /* ignore */
      }
      return updated;
    });
  };

  // Remove every per-job localStorage entry associated with a jobId.
  // Without this, useClipStates / per-job preselections leaked into
  // localStorage forever, bloating storage until QuotaExceeded.
  const _purgeJobScopedStorage = (jobId) => {
    try {
      localStorage.removeItem(`clippyme_clip_states_${jobId}`);
      localStorage.removeItem(`clippyme_preselections_job_${jobId}`);
    } catch {
      /* ignore */
    }
  };

  const deleteFromHistory = (jobId) => {
    setHistory((prev) => {
      const updated = prev.filter((h) => h.jobId !== jobId);
      try {
        localStorage.setItem(HISTORY_KEY, JSON.stringify(updated));
      } catch {
        /* ignore */
      }
      _purgeJobScopedStorage(jobId);
      return updated;
    });
  };

  const clearHistory = () => {
    // Purge every per-job blob we know about before dropping the index.
    setHistory((prev) => {
      for (const entry of prev) {
        if (entry?.jobId) _purgeJobScopedStorage(entry.jobId);
      }
      return [];
    });
    localStorage.removeItem(HISTORY_KEY);
  };

  return { history, setHistory, saveToHistory, deleteFromHistory, clearHistory };
}
