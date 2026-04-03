import React from 'react';
import { ArrowRight, Scan, Move, Captions, Layers, Volume2, Scissors } from 'lucide-react';

const FeatureCard = ({ icon: Icon, title, description, delay = 0 }) => (
  <div
    className="group relative bg-[#0f0f13] rounded-2xl border border-white/5 p-7 hover:border-white/[0.12] transition-all duration-500 overflow-hidden animate-slide-up"
    style={{ animationDelay: `${delay}ms`, animationFillMode: 'both' }}
  >
    {/* Hover glow */}
    <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-700 pointer-events-none"
      style={{ background: 'radial-gradient(ellipse 80% 60% at 50% 0%, rgba(152,80,195,0.06) 0%, transparent 70%)' }}
    />

    <div className="relative z-10">
      <div className="w-11 h-11 rounded-xl border border-white/[0.06] flex items-center justify-center mb-5 group-hover:border-pink-500/20 transition-colors duration-500"
        style={{ background: 'linear-gradient(135deg, rgba(230,66,141,0.08), rgba(152,80,195,0.08), rgba(10,129,217,0.06))' }}
      >
        <Icon size={19} className="text-zinc-400 group-hover:text-white transition-colors" />
      </div>
      <h3 className="text-[15px] font-semibold text-white mb-2 tracking-tight">{title}</h3>
      <p className="text-[13px] text-zinc-500 leading-relaxed">{description}</p>
    </div>
  </div>
);

const StepItem = ({ number, title, description, isLast }) => (
  <div className="flex gap-5">
    <div className="flex flex-col items-center">
      <div className="w-10 h-10 rounded-full flex items-center justify-center text-white text-sm font-bold shrink-0"
        style={{ background: 'linear-gradient(135deg, #e6428d, #9850c3, #675add)' }}
      >
        {number}
      </div>
      {!isLast && (
        <div className="w-px flex-1 bg-gradient-to-b from-purple-500/40 to-transparent mt-3" />
      )}
    </div>
    <div className={`pb-12 ${isLast ? 'pb-0' : ''}`}>
      <h3 className="text-base font-semibold text-white mb-1.5 tracking-tight">{title}</h3>
      <p className="text-sm text-zinc-500 leading-relaxed max-w-sm">{description}</p>
    </div>
  </div>
);

// Cinematic transformation visual
const TransformVisual = () => (
  <div className="flex items-center justify-center gap-8 mt-14 mb-4">
    {/* 16:9 horizontal source */}
    <div className="relative group">
      <div className="w-44 h-[99px] rounded-xl bg-[#0f0f13] border border-white/[0.06] overflow-hidden flex items-center justify-center">
        {/* Fake video content lines */}
        <div className="absolute inset-3 flex flex-col gap-2 opacity-30">
          <div className="h-1.5 w-3/4 rounded-full bg-white/20" />
          <div className="h-1.5 w-1/2 rounded-full bg-white/15" />
          <div className="flex-1 rounded bg-white/5" />
          <div className="h-1.5 w-2/3 rounded-full bg-white/10" />
        </div>
        <span className="text-[10px] text-zinc-600 font-mono relative z-10">16:9</span>
      </div>
      <div className="text-[10px] text-zinc-600 text-center mt-2">Source</div>
    </div>

    {/* Arrow */}
    <div className="flex flex-col items-center gap-1.5">
      <div className="flex items-center gap-1">
        <div className="w-8 h-px" style={{ background: 'linear-gradient(90deg, rgba(230,66,141,0.4), rgba(152,80,195,0.6))' }} />
        <div className="w-8 h-px" style={{ background: 'linear-gradient(90deg, rgba(152,80,195,0.6), rgba(10,129,217,0.4))' }} />
      </div>
      <span className="text-[9px] tracking-widest text-zinc-600 uppercase font-medium">AI</span>
    </div>

    {/* 9:16 vertical output */}
    <div className="relative group">
      <div className="w-[56px] h-[99px] rounded-xl overflow-hidden flex items-center justify-center border border-pink-500/20"
        style={{ background: 'linear-gradient(180deg, rgba(230,66,141,0.05), rgba(152,80,195,0.08), rgba(10,129,217,0.05))' }}
      >
        {/* Fake vertical video content */}
        <div className="absolute inset-2 flex flex-col gap-1.5 opacity-40">
          <div className="flex-1 rounded bg-white/5" />
          <div className="h-1 w-full rounded-full bg-pink-500/20" />
          <div className="h-1 w-3/4 rounded-full bg-purple-500/20" />
        </div>
        <span className="text-[9px] text-pink-400/70 font-mono relative z-10">9:16</span>
      </div>
      {/* Viral score badge */}
      <div className="absolute -top-2 -right-2 w-6 h-6 rounded-full flex items-center justify-center text-[8px] font-bold text-white"
        style={{ background: 'linear-gradient(135deg, #10b981, #059669)' }}
      >
        92
      </div>
      <div className="text-[10px] text-zinc-600 text-center mt-2">Short</div>
    </div>
  </div>
);

const STAT_PILLS = [
  { label: 'Gemini AI', value: 'Powered by' },
  { label: 'YOLOv8', value: 'Face tracking' },
  { label: '6 presets', value: 'Subtitle styles' },
  { label: '20 URLs', value: 'Batch limit' },
];

export default function Landing({ onLaunchApp }) {
  const features = [
    {
      icon: Scan,
      title: "AI Scene Detection",
      description: "Gemini AI analyzes transcripts and scene changes to pinpoint the most engaging viral moments automatically."
    },
    {
      icon: Move,
      title: "Smart Reframing",
      description: "YOLOv8 + MediaPipe face tracking dynamically reframes horizontal video into stabilized 9:16 vertical shots."
    },
    {
      icon: Captions,
      title: "Viral Subtitles",
      description: "Word-level karaoke captions powered by faster-whisper. Six built-in presets with custom font support."
    },
    {
      icon: Layers,
      title: "Batch Processing",
      description: "Submit up to 20 URLs at once. Each video is queued and processed independently with full status tracking."
    },
    {
      icon: Volume2,
      title: "Audio Normalization",
      description: "Two-pass EBU R128 loudnorm at -14 LUFS ensures consistent, broadcast-quality audio across all clips."
    },
    {
      icon: Scissors,
      title: "Smart Cut",
      description: "Automatically removes silences and filler words using intelligent audio analysis and FFmpeg concat demuxer."
    }
  ];

  const steps = [
    {
      title: "Paste a URL or upload a video",
      description: "Drop any YouTube link or local file. yt-dlp handles extraction at the highest available quality."
    },
    {
      title: "AI processes your content",
      description: "The pipeline transcribes, detects scenes, identifies viral moments, and reframes everything to 9:16."
    },
    {
      title: "Download your clips",
      description: "Get polished vertical shorts with subtitles, normalized audio, and cover frames. No watermarks."
    }
  ];

  return (
    <div className="min-h-screen text-zinc-300 font-sans selection:bg-purple-500/20" style={{ backgroundColor: '#050507' }}>

      {/* Floating ambient orbs */}
      <div className="fixed inset-0 pointer-events-none -z-10 overflow-hidden">
        {/* Top center blue orb */}
        <div
          className="absolute rounded-full animate-float"
          style={{
            width: '600px',
            height: '600px',
            top: '-200px',
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'radial-gradient(ellipse, rgba(10,129,217,0.06) 0%, transparent 70%)',
            animationDuration: '8s',
          }}
        />
        {/* Left pink orb */}
        <div
          className="absolute rounded-full animate-float"
          style={{
            width: '400px',
            height: '400px',
            top: '20%',
            left: '-100px',
            background: 'radial-gradient(ellipse, rgba(230,66,141,0.05) 0%, transparent 70%)',
            animationDuration: '11s',
            animationDelay: '-3s',
          }}
        />
        {/* Right purple orb */}
        <div
          className="absolute rounded-full animate-float"
          style={{
            width: '350px',
            height: '350px',
            top: '30%',
            right: '-80px',
            background: 'radial-gradient(ellipse, rgba(152,80,195,0.05) 0%, transparent 70%)',
            animationDuration: '9s',
            animationDelay: '-5s',
          }}
        />
      </div>

      {/* Navigation */}
      <nav className="fixed top-0 w-full z-50 backdrop-blur-xl border-b border-white/[0.03]" style={{ backgroundColor: 'rgba(5,5,7,0.8)' }}>
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2.5 cursor-pointer" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
            <img src="/logo.svg" alt="ClippyMe" className="w-7 h-7" />
            <span className="text-base font-semibold text-white tracking-tight">ClippyMe</span>
          </div>

          <div className="hidden md:flex items-center gap-8 text-[13px] text-zinc-500">
            <a href="#features" className="hover:text-white transition-colors">Features</a>
            <a href="#how-it-works" className="hover:text-white transition-colors">How it works</a>
          </div>

          <button
            onClick={onLaunchApp}
            className="text-[13px] font-medium text-white bg-white/[0.06] hover:bg-white/[0.1] border border-white/[0.08] px-4 py-2 rounded-lg transition-all"
          >
            Open App
          </button>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative pt-44 pb-20 px-6">
        <div className="max-w-5xl mx-auto flex flex-col items-center text-center">

          <img
            src="/logo.svg"
            alt="ClippyMe"
            className="w-20 h-20 mb-8 animate-float"
            style={{ animationDuration: '7s' }}
          />

          <h1 className="text-5xl md:text-7xl font-bold tracking-tight mb-6 leading-[1.05]">
            <span
              className="bg-clip-text text-transparent animate-gradient-shift"
              style={{
                backgroundImage: 'linear-gradient(135deg, #ec4899, #a855f7, #3b82f6, #ec4899)',
              }}
            >
              ClippyMe
            </span>
          </h1>

          <p className="text-xl text-zinc-400 max-w-lg mb-3 leading-relaxed">
            Transform any video into viral shorts with AI
          </p>
          <p className="text-sm text-zinc-600 max-w-sm mb-10">
            Self-hosted · No watermarks · Gemini-powered
          </p>

          <button
            onClick={onLaunchApp}
            className="group flex items-center gap-2.5 text-white font-semibold px-8 py-4 rounded-full text-base transition-all duration-300 hover:shadow-lg hover:shadow-purple-500/25 active:scale-[0.97]"
            style={{
              backgroundImage: 'linear-gradient(135deg, #ec4899, #a855f7)',
            }}
          >
            Start Creating
            <ArrowRight size={18} className="group-hover:translate-x-1 transition-transform" />
          </button>

          {/* Transformation visual */}
          <TransformVisual />

          {/* Stat pills */}
          <div className="flex flex-wrap items-center justify-center gap-3 mt-8">
            {STAT_PILLS.map(({ label, value }) => (
              <div key={label} className="flex items-center gap-2 px-3.5 py-1.5 rounded-full border border-white/[0.06] bg-white/[0.02] text-[11px]">
                <span className="text-zinc-500">{value}</span>
                <span className="text-white font-medium">{label}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="py-28 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-bold text-white tracking-tight mb-4">Everything you need</h2>
            <p className="text-zinc-500 text-base max-w-md mx-auto">A complete pipeline from raw video to polished vertical shorts, powered by state-of-the-art AI.</p>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {features.map((feature, i) => (
              <FeatureCard key={i} {...feature} delay={i * 60} />
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how-it-works" className="py-28 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-bold text-white tracking-tight mb-4">How it works</h2>
            <p className="text-zinc-500 text-base max-w-md mx-auto">Three steps. One pipeline. Unlimited clips.</p>
          </div>
          <div className="max-w-md mx-auto">
            {steps.map((step, i) => (
              <StepItem
                key={i}
                number={i + 1}
                title={step.title}
                description={step.description}
                isLast={i === steps.length - 1}
              />
            ))}
          </div>
        </div>
      </section>

      {/* Bottom CTA */}
      <section className="py-32 px-6">
        <div className="max-w-5xl mx-auto text-center">
          {/* Separator glow */}
          <div className="w-32 h-px mx-auto mb-16" style={{ background: 'linear-gradient(90deg, transparent, rgba(152,80,195,0.4), transparent)' }} />

          <h2 className="text-4xl md:text-5xl font-bold text-white tracking-tight mb-6">Ready to go viral?</h2>
          <p className="text-zinc-500 text-base mb-10 max-w-md mx-auto">Deploy in minutes with Docker. Start turning long-form content into scroll-stopping shorts.</p>
          <button
            onClick={onLaunchApp}
            className="group inline-flex items-center gap-2.5 text-white font-semibold px-8 py-4 rounded-full text-base transition-all duration-300 hover:shadow-lg hover:shadow-purple-500/25 active:scale-[0.97]"
            style={{
              backgroundImage: 'linear-gradient(135deg, #ec4899, #a855f7)',
            }}
          >
            Start Creating
            <ArrowRight size={18} className="group-hover:translate-x-1 transition-transform" />
          </button>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/[0.04] py-8 px-6">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-2 text-zinc-600 text-sm">
            <span className="font-medium">ClippyMe</span>
          </div>
          <span className="text-xs text-zinc-700">v1.0</span>
        </div>
      </footer>
    </div>
  );
}
