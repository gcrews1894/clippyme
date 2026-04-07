import { getApiUrl } from '../config';

export async function pollJob(jobId) {
  const res = await fetch(getApiUrl(`/api/status/${jobId}`));
  if (!res.ok) throw new Error('Status check failed');
  return res.json();
}
