import React, { useState } from 'react';
import { Download, Share2, Instagram, Youtube, Video, CheckCircle, AlertCircle, X, Loader2 } from 'lucide-react';

export default function ResultCard({ clip, index, jobId, uploadPostKey, uploadUserId }) {
    const [showModal, setShowModal] = useState(false);
    const [platforms, setPlatforms] = useState({
        tiktok: true,
        instagram: true,
        youtube: true
    });
    const [posting, setPosting] = useState(false);
    const [postResult, setPostResult] = useState(null); // { success: boolean, msg: string }

    const handlePost = async () => {
        if (!uploadPostKey || !uploadUserId) {
            setPostResult({ success: false, msg: "Missing API Key or User ID. Configure them at the top." });
            return;
        }

        const selectedPlatforms = Object.keys(platforms).filter(k => platforms[k]);
        if (selectedPlatforms.length === 0) {
            setPostResult({ success: false, msg: "Select at least one platform." });
            return;
        }

        setPosting(true);
        setPostResult(null);

        try {
            const res = await fetch('/api/social/post', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    clip_index: index,
                    api_key: uploadPostKey,
                    user_id: uploadUserId,
                    platforms: selectedPlatforms
                })
            });

            if (!res.ok) {
                const errText = await res.text();
                // Try parsing JSON error
                try {
                    const jsonErr = JSON.parse(errText);
                    throw new Error(jsonErr.detail || errText);
                } catch (e) {
                    throw new Error(errText);
                }
            }

            const data = await res.json();
            setPostResult({ success: true, msg: "Posted successfully! Check your social accounts." });
            setTimeout(() => {
                setShowModal(false);
                setPostResult(null);
            }, 3000);

        } catch (e) {
            setPostResult({ success: false, msg: `Failed: ${e.message}` });
        } finally {
            setPosting(false);
        }
    };

    return (
        <div className="glass-panel overflow-hidden animate-[fadeIn_0.5s_ease-out]" style={{ animationDelay: `${index * 0.1}s` }}>
            <div className="grid md:grid-cols-2 gap-0">
                <div className="bg-black/50 aspect-[9/16] relative group">
                    <video
                        src={clip.video_url}
                        controls
                        className="w-full h-full object-contain"
                        loop
                    />
                    <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <a
                            href={clip.video_url}
                            download
                            className="p-2 bg-black/60 backdrop-blur rounded-lg text-white hover:bg-black/80 inline-flex"
                        >
                            <Download size={16} />
                        </a>
                    </div>
                </div>

                <div className="p-6 flex flex-col h-full">
                    <div className="mb-4">
                        <div className="flex items-center gap-2 mb-2">
                            <span className="text-xs font-bold px-2 py-1 bg-primary/20 text-primary rounded-md uppercase tracking-wider">
                                Clip {index + 1}
                            </span>
                            <span className="text-xs text-zinc-500 font-mono">
                                {clip.start}s - {clip.end}s
                            </span>
                            <span className="ml-auto text-xs font-medium text-red-400 flex items-center gap-1">
                                <Youtube size={12} /> YouTube Short Title
                            </span>
                        </div>
                        <h3 className="text-xl font-bold leading-tight mb-4 text-white">
                            {clip.video_title_for_youtube_short || "Viral Clip"}
                        </h3>
                    </div>

                    <div className="space-y-4 flex-1">
                        <div className="space-y-1">
                            <div className="flex items-center gap-2 text-xs font-medium text-pink-400">
                                <Instagram size={14} /> Instagram Description
                            </div>
                            <div className="p-3 bg-white/5 rounded-lg text-sm text-zinc-300 leading-relaxed border border-white/5 line-clamp-3 hover:line-clamp-none transition-all">
                                {clip.video_description_for_instagram}
                            </div>
                        </div>

                        <div className="space-y-1">
                            <div className="flex items-center gap-2 text-xs font-medium text-cyan-400">
                                <Video size={14} /> TikTok Description
                            </div>
                            <div className="p-3 bg-white/5 rounded-lg text-sm text-zinc-300 leading-relaxed border border-white/5 line-clamp-3 hover:line-clamp-none transition-all">
                                {clip.video_description_for_tiktok || clip.video_description_for_instagram}
                            </div>
                        </div>
                    </div>

                    <div className="mt-6 pt-4 border-t border-white/10 flex gap-2">
                        <button
                            onClick={() => setShowModal(true)}
                            className="flex-1 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2 text-white"
                        >
                            <Share2 size={16} /> Post to Socials
                        </button>
                        <a
                            href={clip.video_url}
                            download
                            className="flex-1 py-2 bg-primary/10 hover:bg-primary/20 text-primary rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
                        >
                            <Download size={16} /> Download
                        </a>
                    </div>
                </div>
            </div>

            {/* Modal */}
            {showModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out]">
                    <div className="bg-zinc-900 border border-white/10 p-6 rounded-2xl w-full max-w-sm shadow-2xl relative">
                        <button
                            onClick={() => setShowModal(false)}
                            className="absolute top-4 right-4 text-zinc-500 hover:text-white"
                        >
                            <X size={20} />
                        </button>

                        <h3 className="text-xl font-bold text-white mb-4">Post to Socials</h3>

                        {!uploadPostKey && (
                            <div className="mb-4 p-3 bg-yellow-500/10 border border-yellow-500/20 text-yellow-200 text-sm rounded-lg flex items-start gap-2">
                                <AlertCircle size={16} className="mt-0.5 shrink-0" />
                                <div>
                                    Please configure your Upload-Post API Key at the top of the page first.
                                </div>
                            </div>
                        )}

                        <div className="space-y-3 mb-6">
                            <label className="flex items-center gap-3 p-3 bg-white/5 rounded-lg cursor-pointer hover:bg-white/10 transition-colors border border-white/5">
                                <input
                                    type="checkbox"
                                    checked={platforms.tiktok}
                                    onChange={e => setPlatforms({ ...platforms, tiktok: e.target.checked })}
                                    className="w-4 h-4 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                                />
                                <div className="flex items-center gap-2">
                                    <Video size={18} className="text-cyan-400" />
                                    <span className="text-sm font-medium text-white">TikTok</span>
                                </div>
                            </label>

                            <label className="flex items-center gap-3 p-3 bg-white/5 rounded-lg cursor-pointer hover:bg-white/10 transition-colors border border-white/5">
                                <input
                                    type="checkbox"
                                    checked={platforms.instagram}
                                    onChange={e => setPlatforms({ ...platforms, instagram: e.target.checked })}
                                    className="w-4 h-4 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                                />
                                <div className="flex items-center gap-2">
                                    <Instagram size={18} className="text-pink-400" />
                                    <span className="text-sm font-medium text-white">Instagram</span>
                                </div>
                            </label>

                            <label className="flex items-center gap-3 p-3 bg-white/5 rounded-lg cursor-pointer hover:bg-white/10 transition-colors border border-white/5">
                                <input
                                    type="checkbox"
                                    checked={platforms.youtube}
                                    onChange={e => setPlatforms({ ...platforms, youtube: e.target.checked })}
                                    className="w-4 h-4 rounded border-zinc-600 bg-black/50 text-primary focus:ring-primary"
                                />
                                <div className="flex items-center gap-2">
                                    <Youtube size={18} className="text-red-400" />
                                    <span className="text-sm font-medium text-white">YouTube Shorts</span>
                                </div>
                            </label>
                        </div>

                        {postResult && (
                            <div className={`mb-4 p-3 rounded-lg text-sm flex items-start gap-2 ${postResult.success ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
                                {postResult.success ? <CheckCircle size={16} className="mt-0.5 shrink-0" /> : <AlertCircle size={16} className="mt-0.5 shrink-0" />}
                                <div>{postResult.msg}</div>
                            </div>
                        )}

                        <button
                            onClick={handlePost}
                            disabled={posting || !uploadPostKey}
                            className="w-full py-3 bg-primary hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed rounded-xl text-white font-bold transition-all flex items-center justify-center gap-2"
                        >
                            {posting ? (
                                <>
                                    <Loader2 size={18} className="animate-spin" /> Publishing...
                                </>
                            ) : (
                                <>
                                    <Share2 size={18} /> Publish Now
                                </>
                            )}
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}
