// ClippyMe redesign — shared subject-mode reframe controls.
//
// Dumb, fully-controlled (layerControls / hookStyle pattern): takes the current
// `smooth` (bool) + `hold` (frames) and emits partials via onChange — never owns
// state, never applies defaults. Rendered by BOTH the Create recipe and the
// EditClipModal Reframe tab so the subject-smoothing knobs aren't duplicated per
// surface. `variant` supplies per-surface chrome, like SubtitleControls.
//
// Only meaningful in subject (FrameShift) mode — the caller gates rendering on
// that. The hold row is hidden when smoothing is off. Backend value is a frame
// count; labels map at 30fps (approximate on 24/25/60fps sources), matching the
// documented default "45 ≈ 1.5s @30fps".
import { Segmented, Switch, Icon } from './primitives';

export const HOLD_DEFAULT = 45; // frames (~1.5s @30fps)

export const HOLD_OPTS = [
  { id: 0, label: 'Off' },
  { id: 15, label: '0.5s' },
  { id: 30, label: '1.0s' },
  { id: 45, label: '1.5s' },
  { id: 60, label: '2.0s' },
  { id: 75, label: '2.5s' },
  { id: 90, label: '3.0s' },
];

const DESC = 'Follows one steadied path instead of re-cropping every frame';
const HOLD_DESC = 'Keep the last position when detection drops briefly';

export function SubjectSmoothControls({ smooth, hold, onChange, variant = 'create' }) {
  const on = smooth !== false; // default on
  const holdVal = HOLD_OPTS.some((o) => o.id === hold) ? hold : HOLD_DEFAULT;
  const holdRow = on && (
    <div className="field" style={{ marginTop: 10 }}>
      <span className="field-label" style={{ marginBottom: 9, display: 'flex' }}>Hold through dropouts</span>
      <Segmented full value={holdVal} onChange={(v) => onChange({ subjectHold: v })} options={HOLD_OPTS} />
      <div className="eo-d" style={{ marginTop: 6 }}>{HOLD_DESC}</div>
    </div>
  );

  if (variant === 'edit') {
    return (
      <div className="field" style={{ marginTop: 10 }}>
        <div className="edit-opt">
          <div className="eo-ico"><Icon n="audio-lines" /></div>
          <div className="eo-txt"><div className="eo-t">Smooth subject tracking</div><div className="eo-d">{DESC}</div></div>
          <Switch on={on} onChange={(v) => onChange({ subjectSmooth: v })} />
        </div>
        {holdRow}
      </div>
    );
  }

  // create variant — matches the recipe's .opt row chrome
  return (
    <>
      <div className={'opt' + (on ? ' on' : '')}>
        <div className="oico"><Icon n="audio-lines" /></div>
        <div className="otxt"><div className="ot">Smooth subject tracking</div><div className="od">{DESC}</div></div>
        <div className="r"><Switch on={on} onChange={(v) => onChange({ subjectSmooth: v })} /></div>
      </div>
      {holdRow}
    </>
  );
}
