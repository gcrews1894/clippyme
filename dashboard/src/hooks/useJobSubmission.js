import { submitProcessJob, submitBatchJob } from '../lib/api';
import { getApiUrl } from '../config';

/**
 * Custom hook factory that returns process/batch submission handlers.
 * Receives the state setters from App.jsx so handlers stay declarative.
 */
export function useJobSubmission({
  apiKey,
  setShowKeyModal,
  setStatus,
  setLogs,
  setResults,
  setProcessingMedia,
  setPreselections,
  setJobId,
}) {
  const handleProcess = async (data) => {
    if (!apiKey) {
      setShowKeyModal(true);
      return;
    }
    setStatus('processing');
    setLogs(['Initializing engine...']);
    setResults(null);
    setProcessingMedia(data);
    if (data.preselections) setPreselections(data.preselections);

    try {
      const resData = await submitProcessJob(data, apiKey);
      setJobId(resData.job_id);
    } catch (e) {
      setStatus('error');
      setLogs((l) => [...l, `Error: ${e.message}`]);
    }
  };

  const handleBatchProcess = async (data) => {
    if (!apiKey) {
      setShowKeyModal(true);
      return;
    }
    setStatus('processing');
    setLogs(['Launching batch processing...']);
    setResults(null);
    if (data.preselections) setPreselections(data.preselections);

    try {
      const resData = await submitBatchJob(data, apiKey);
      setLogs((l) => [...l, `Batch ${resData.batch_id}: ${resData.total} jobs queued`]);

      const batchId = resData.batch_id;
      const pollBatch = setInterval(async () => {
        try {
          const statusRes = await fetch(getApiUrl(`/api/batch/${batchId}`));
          if (!statusRes.ok) return;
          const statusData = await statusRes.json();
          setLogs([
            `Batch progress: ${statusData.completed}/${statusData.total} completed, ${statusData.failed} failed`,
          ]);
          if (statusData.completed + statusData.failed >= statusData.total) {
            clearInterval(pollBatch);
            setStatus('completed');
            setLogs((l) => [
              ...l,
              `Batch complete! ${statusData.completed} succeeded, ${statusData.failed} failed.`,
            ]);
          }
        } catch {
          /* ignore poll errors */
        }
      }, 3000);
    } catch (e) {
      setStatus('error');
      setLogs((l) => [...l, `Batch error: ${e.message}`]);
    }
  };

  return { handleProcess, handleBatchProcess };
}
