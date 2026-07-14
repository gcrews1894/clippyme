// Background clip-reprocess orchestration, extracted from RedesignApp so the
// routing rules (reframe-only vs compose-only vs both, toggle-gated params,
// partial-failure recovery) are unit-testable without mounting the app.
//
// `api` is injected ({ reframeClip, composeClip }) — production passes the
// realApi functions, tests pass fakes.

export async function runApplyEdit({ jobId, idx, params, api, updateClipState, pushToast, now = Date.now }) {
  const { reframeMode, baseMode, subjectSmooth, subjectHold, subjectSettingsChanged,
    toggles, subtitleParams, hookParams, logoParams, gradeParams, dropRanges } = params;
  // Re-reframe on a mode change OR (subject mode) a smoothing-knob change — the
  // latter still overwrites the clip via main.py --reframe-only.
  const reframeChanged = reframeMode !== baseMode || !!subjectSettingsChanged;
  const anyCompose = !!(toggles.smartcut || toggles.subtitles || toggles.hook || toggles.logo || toggles.grade);

  // Persist the user's choices + flip the card into its processing state up
  // front (so the badge/preview already reflect the new reframe mode).
  updateClipState(idx, { reframeMode, subjectSmooth, subjectHold, toggles, subtitleParams, hookParams, logoParams, gradeParams, dropRanges,
    processing: reframeChanged || anyCompose });

  if (!reframeChanged && !anyCompose) {
    pushToast('success', `Clip ${idx + 1} updated`);
    return;
  }

  let reframeApplied = false;
  try {
    if (reframeChanged) {
      // Send the smoothing overrides only in subject mode (undefined elsewhere
      // → the backend reuses the job's persisted values).
      const extra = reframeMode === 'subject' ? { subjectSmooth, subjectHold } : {};
      await api.reframeClip(jobId, idx, reframeMode, extra);
      reframeApplied = true;
      // Reframe overwrites the clip on disk → bust the cache + drop any stale
      // composed preview so the card re-fetches the freshly framed clip.
      updateClipState(idx, { reframeBust: now(), previewUrl: undefined });
    }
    if (anyCompose) {
      const { composed_url } = await api.composeClip(jobId, idx, {
        toggles,
        hook_params: toggles.hook ? hookParams : {},
        subtitle_params: toggles.subtitles ? subtitleParams : {},
        logo_params: toggles.logo ? logoParams : {},
        grade_params: toggles.grade ? gradeParams : {},
        drop_ranges: toggles.smartcut ? (dropRanges || []) : [],
      });
      updateClipState(idx, { previewUrl: composed_url, previewBust: now(), processing: false });
    } else {
      updateClipState(idx, { processing: false });
    }
    pushToast('success', `Clip ${idx + 1} updated`);
  } catch (err) {
    // Partial success: reframe already overwrote the file, so keep its
    // cache-buster even though composing failed — otherwise the card serves
    // the pre-reframe cached URL forever.
    if (reframeApplied) {
      updateClipState(idx, { reframeBust: now(), previewUrl: undefined, processing: false });
      pushToast('error', `Clip ${idx + 1}: reframed, but composing the layers failed.`);
      return;
    }
    updateClipState(idx, { processing: false });
    pushToast('error', err?.status === 409
      ? `Clip ${idx + 1} is too old to reframe — reprocess the video first.`
      : `Clip ${idx + 1} reprocess failed: ` + String(err?.message || err).slice(0, 50));
  }
}
