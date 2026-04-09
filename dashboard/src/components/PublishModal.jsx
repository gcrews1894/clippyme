import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Send, Loader2, Calendar, Clock, Zap } from 'lucide-react';
import { toast } from 'sonner';
import { getApiUrl } from '../config';

/**
 * PublishModal — schedule a clip on TikTok / Instagram / YouTube via Zernio.
 *
 * Props:
 *   isOpen, onClose
 *   jobId, clipIndex
 *   defaultTitle, defaultCaption
 *   videoUrl (for preview)
 *   composeBeforePublish: { toggles, hookParams, subtitleParams } | null
 *     If provided, the backend will run a fresh compose pass before upload.
 */
export default function PublishModal({
    isOpen, onClose,
    jobId, clipIndex,
    defaultTitle = '', defaultCaption = '',
    videoUrl,
    composeBeforePublish = null,
    onPublished = null,
}) {
    // Helpers — build YYYY-MM-DD for today and a datetime-local string
    // for tomorrow at 09:00 (the default pre-fill when the user switches
    // to "Pick time"). Both are computed in LOCAL time so the DOM inputs
    // consume them without TZ offset drift.
    const todayISO = () => {
        const d = new Date();
        const o = d.getTimezoneOffset();
        return new Date(d.getTime() - o * 60_000).toISOString().slice(0, 10);
    };
    const tomorrowAt9LocalISO = () => {
        const d = new Date();
        d.setDate(d.getDate() + 1);
        d.setHours(9, 0, 0, 0);
        const o = d.getTimezoneOffset();
        return new Date(d.getTime() - o * 60_000).toISOString().slice(0, 16);
    };

    const [title, setTitle] = useState(defaultTitle);
    const [caption, setCaption] = useState(defaultCaption);
    const [scheduleMode, setScheduleMode] = useState('now');
    // Auto mode now accepts an explicit start day (defaults to today).
    // The backend SmartScheduler will find the best slot within that
    // day's prime-time windows, avoiding collisions with posts already
    // scheduled for that day.
    const [autoStartDate, setAutoStartDate] = useState(todayISO());
    // Manual mode pre-fills with tomorrow @ 09:00 local — the user can
    // tweak it to whatever they want, but they don't have to type the
    // full ISO string from scratch anymore.
    const [manualDateTime, setManualDateTime] = useState(tomorrowAt9LocalISO());
    const [enabled, setEnabled] = useState({ tiktok: true, instagram: true, youtube: true });
    const [zernioConfig, setZernioConfig] = useState(null);
    const [publishing, setPublishing] = useState(false);
    const [result, setResult] = useState(null);

    useEffect(() => {
        if (!isOpen) return;
        setTitle(defaultTitle);
        setCaption(defaultCaption);
        // Reset the schedule pickers to fresh defaults every time the
        // modal re-opens, so the user never ends up with a stale date
        // from a previous session.
        setAutoStartDate(todayISO());
        setManualDateTime(tomorrowAt9LocalISO());
        setResult(null);
        fetch(getApiUrl('/api/config/zernio'))
            .then((r) => r.ok ? r.json() : null)
            .then(setZernioConfig)
            .catch(() => setZernioConfig(null));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isOpen, defaultTitle, defaultCaption]);

    if (!isOpen) return null;

    const accounts = zernioConfig?.accounts || {};
    const isConfigured = !!zernioConfig?.configured;
    const platformsAvailable = {
        tiktok: !!accounts.tiktok,
        instagram: !!accounts.instagram,
        youtube: !!accounts.youtube,
    };
    const enabledCount = Object.entries(enabled)
        .filter(([k, v]) => v && platformsAvailable[k])
        .length;

    const handlePublish = async () => {
        if (!isConfigured) {
            toast.error('Configure your Zernio API key in Settings first');
            return;
        }
        if (enabledCount === 0) {
            toast.error('Select at least one platform');
            return;
        }
        if (scheduleMode === 'manual' && !manualDateTime) {
            toast.error('Pick a date/time for manual scheduling');
            return;
        }

        // Zernio platform payload rules (per docs.zernio.com):
        //   - `content` is the universal post text shown on all platforms
        //   - `title` is required ONLY for YouTube, sent at the root level
        //   - `tiktokSettings` is a ROOT body field, NOT platformSpecificData
        //   - `platformSpecificData` holds per-platform data Zernio forwards
        //     verbatim to each platform's API (e.g. YouTube visibility,
        //     Instagram shareToFeed). Empty dict = sensible defaults.
        //
        // Previous bug: we were wrapping tiktokSettings inside
        // platformSpecificData and duplicating YouTube `title` both at root
        // and inside platformSpecificData, which confused Zernio. Cleaned up.
        const platformTargets = [];
        if (enabled.tiktok && accounts.tiktok) {
            platformTargets.push({
                platform: 'tiktok',
                accountId: accounts.tiktok,
                // TikTok caption comes from root `content` (below). No title
                // concept on TikTok — if the user typed a title without a
                // caption, the backend will use the title as content.
                platformSpecificData: {},
            });
        }
        if (enabled.instagram && accounts.instagram) {
            platformTargets.push({
                platform: 'instagram',
                accountId: accounts.instagram,
                // shareToFeed=true so video clips land on the main grid in
                // addition to Reels. Instagram Reels auto-detected by media
                // type by Zernio.
                platformSpecificData: { shareToFeed: true },
            });
        }
        if (enabled.youtube && accounts.youtube) {
            platformTargets.push({
                platform: 'youtube',
                accountId: accounts.youtube,
                // Title is sent at the root. Here we only specify per-video
                // YouTube flags.
                platformSpecificData: {
                    visibility: 'public',
                    madeForKids: false,
                },
            });
        }

        // Ensure TikTok and Instagram always receive some text: if the user
        // left the caption blank, fall back to the title. The backend will
        // also apply this fallback (belt-and-suspenders) but doing it here
        // means the user sees the exact content that will be posted in the
        // response if there's an error.
        const effectiveCaption = (caption && caption.trim()) || title || '';

        const body = {
            title,
            caption: effectiveCaption,
            platforms: platformTargets,
            schedule_mode: scheduleMode,
            timezone: zernioConfig?.timezone || 'Europe/Rome',
            // TikTok settings at the root — Zernio expects them there, not
            // nested inside platformSpecificData.
            tiktok_settings: enabled.tiktok && accounts.tiktok ? {
                privacy_level: 'PUBLIC_TO_EVERYONE',
                allow_comment: true,
                allow_duet: true,
                allow_stitch: true,
                content_preview_confirmed: true,
                express_consent_given: true,
            } : undefined,
        };
        if (scheduleMode === 'manual') {
            // ISO 8601 from datetime-local input (no timezone offset → backend treats it as local)
            body.scheduled_for = new Date(manualDateTime).toISOString();
        } else if (scheduleMode === 'auto' && autoStartDate) {
            // Auto slot: tell the SmartScheduler which day to start from.
            // Backend will pick the best time within the day's prime-time
            // windows, bumping to tomorrow automatically if the picked
            // day is already too far into the night to fit a legitimate
            // slot (handled by publish_clip in social_publisher.py).
            body.start_date = autoStartDate;
        }
        if (composeBeforePublish) {
            body.compose_first = true;
            body.toggles = composeBeforePublish.toggles;
            body.hook_params = composeBeforePublish.hookParams;
            body.subtitle_params = composeBeforePublish.subtitleParams;
        }

        setPublishing(true);
        try {
            const res = await fetch(getApiUrl(`/api/publish/${jobId}/${clipIndex}`), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            setResult(data);
            if (onPublished) onPublished(data);
            toast.success(
                scheduleMode === 'now'
                    ? 'Published successfully!'
                    : `Scheduled for ${data.scheduled_for || 'auto-picked slot'}`
            );
        } catch (e) {
            toast.error(`Publish failed: ${e.message}`);
        } finally {
            setPublishing(false);
        }
    };

    return createPortal(
        <div
            className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in"
            onClick={onClose}
        >
            <div
                className="bg-[oklch(9%_0.006_260)] border border-white/10 rounded-[3px] w-full max-w-2xl shadow-elevated relative flex flex-col max-h-[90vh] overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                <button
                    onClick={onClose}
                    className="absolute top-4 right-4 z-30 p-1.5 rounded-[3px] bg-white/5 hover:bg-white/10 transition-colors"
                >
                    <X size={18} className="text-zinc-400" />
                </button>

                <div className="px-6 pt-6 pb-4 border-b border-white/5">
                    <h3 className="text-lg font-display font-bold text-white flex items-center gap-2">
                        <Send size={18} className="text-accent-pink" />
                        Publish to social
                    </h3>
                    <p className="text-xs text-zinc-500 mt-0.5">
                        Schedule this clip on TikTok, Instagram and YouTube via Zernio.
                    </p>
                </div>

                <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
                    {zernioConfig === null && (
                        <div className="px-4 py-3 rounded-[3px] bg-white/[0.02] border border-white/5 text-zinc-500 text-xs flex items-center gap-2">
                            <Loader2 size={12} className="animate-spin" /> Checking Zernio configuration…
                        </div>
                    )}
                    {zernioConfig !== null && !isConfigured && (
                        <div className="px-4 py-3 rounded-[3px] bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs space-y-2">
                            <p>
                                ⚠ Zernio is not configured. You need an API key + at least one connected social account before you can publish.
                            </p>
                            <button
                                type="button"
                                onClick={() => {
                                    onClose();
                                    // Tab change is owned by App; let the user navigate manually for now.
                                    toast.info('Open Settings → Social Publishing to configure Zernio.');
                                }}
                                className="text-[11px] font-semibold text-amber-200 hover:text-white underline underline-offset-2"
                            >
                                Open Settings →
                            </button>
                        </div>
                    )}

                    {/* Title */}
                    <div className="space-y-1.5">
                        <label className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">Title</label>
                        <input
                            type="text"
                            value={title}
                            onChange={(e) => setTitle(e.target.value)}
                            maxLength={100}
                            className="w-full bg-white/[0.03] border border-white/5 rounded-[3px] px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500/30"
                            placeholder="YouTube title (max 100 chars)"
                        />
                    </div>

                    {/* Caption */}
                    <div className="space-y-1.5">
                        <label className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">Caption</label>
                        <textarea
                            value={caption}
                            onChange={(e) => setCaption(e.target.value)}
                            rows={4}
                            maxLength={2200}
                            className="w-full bg-white/[0.03] border border-white/5 rounded-[3px] px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500/30 resize-none"
                            placeholder="Caption / description shown on all platforms"
                        />
                        <p className="text-[10px] text-zinc-600 text-right">{caption.length} / 2200</p>
                    </div>

                    {/* Platforms */}
                    <div className="space-y-2">
                        <label className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">Platforms</label>
                        <div className="grid grid-cols-3 gap-2">
                            {[
                                { id: 'tiktok', label: 'TikTok' },
                                { id: 'instagram', label: 'Instagram' },
                                { id: 'youtube', label: 'YouTube' },
                            ].map(({ id, label }) => {
                                const available = platformsAvailable[id];
                                const active = enabled[id] && available;
                                return (
                                    <button
                                        key={id}
                                        type="button"
                                        onClick={() => available && setEnabled({ ...enabled, [id]: !enabled[id] })}
                                        disabled={!available}
                                        className={`py-2.5 px-3 rounded-[3px] text-xs font-medium border transition-all ${
                                            active
                                                ? 'bg-accent-pink/20 text-accent-pink border-accent-pink/30'
                                                : available
                                                    ? 'bg-white/[0.02] text-zinc-500 border-white/5 hover:text-zinc-300'
                                                    : 'bg-white/[0.01] text-zinc-700 border-white/5 cursor-not-allowed'
                                        }`}
                                    >
                                        {label}
                                        {!available && <span className="block text-[9px] mt-0.5">No account ID</span>}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {/* Schedule mode */}
                    <div className="space-y-2">
                        <label className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider">When</label>
                        <div className="grid grid-cols-3 gap-2">
                            {[
                                { id: 'now', label: 'Now', icon: Zap },
                                { id: 'auto', label: 'Auto slot', icon: Clock },
                                { id: 'manual', label: 'Pick time', icon: Calendar },
                            ].map(({ id, label, icon: Icon }) => (
                                <button
                                    key={id}
                                    type="button"
                                    onClick={() => setScheduleMode(id)}
                                    className={`py-2.5 px-3 rounded-[3px] text-xs font-medium border transition-all flex items-center justify-center gap-1.5 ${
                                        scheduleMode === id
                                            ? 'bg-accent-pink/20 text-accent-pink border-accent-pink/30'
                                            : 'bg-white/[0.02] text-zinc-500 border-white/5 hover:text-zinc-300'
                                    }`}
                                >
                                    <Icon size={12} />
                                    {label}
                                </button>
                            ))}
                        </div>
                        {scheduleMode === 'manual' && (
                            <input
                                type="datetime-local"
                                value={manualDateTime}
                                onChange={(e) => setManualDateTime(e.target.value)}
                                className="w-full bg-white/[0.03] border border-white/5 rounded-[3px] px-3 py-2 text-xs text-white focus:outline-none focus:ring-2 focus:ring-blue-500/30 mt-2"
                            />
                        )}
                        {scheduleMode === 'auto' && (
                            <div className="space-y-1.5 mt-2">
                                <label className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
                                    Start day for the smart slot
                                </label>
                                <input
                                    type="date"
                                    value={autoStartDate}
                                    min={todayISO()}
                                    onChange={(e) => setAutoStartDate(e.target.value)}
                                    className="w-full bg-white/[0.03] border border-white/5 rounded-[3px] px-3 py-2 text-xs text-white focus:outline-none focus:ring-2 focus:ring-blue-500/30"
                                />
                                <p className="text-[10px] text-zinc-600 leading-snug">
                                    Defaults to today. The smart scheduler picks the optimal slot within that day's prime-time windows, avoiding collisions with your other scheduled posts. If today is already past the prime-time cutoff, it bumps to the next day automatically.
                                </p>
                            </div>
                        )}
                    </div>

                    {/* Result */}
                    {result && (
                        <div className="px-4 py-3 rounded-[3px] bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-xs space-y-1">
                            <p>✅ Post created — id: <code className="text-[10px] bg-black/20 px-1 rounded">{result.post_id || '?'}</code></p>
                            {result.scheduled_for && <p>Scheduled for: {result.scheduled_for}</p>}
                        </div>
                    )}
                </div>

                <div className="px-6 py-4 border-t border-white/5 flex items-center justify-between bg-black/20">
                    <p className="text-[11px] text-zinc-500">
                        {enabledCount} platform{enabledCount === 1 ? '' : 's'} selected
                    </p>
                    <button
                        type="button"
                        onClick={handlePublish}
                        disabled={publishing || !isConfigured || enabledCount === 0}
                        className="flex items-center gap-2 px-5 py-2.5 rounded-[3px] bg-gradient-to-r from-accent-pink to-accent-purple text-white text-sm font-semibold shadow-glow-pink disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                    >
                        {publishing ? (
                            <>
                                <Loader2 size={14} className="animate-spin" />
                                Publishing...
                            </>
                        ) : (
                            <>
                                <Send size={14} />
                                {scheduleMode === 'now' ? 'Publish now' : 'Schedule'}
                            </>
                        )}
                    </button>
                </div>
            </div>
        </div>,
        document.body
    );
}
