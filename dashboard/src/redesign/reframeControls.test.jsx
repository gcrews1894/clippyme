// SubjectSmoothControls — the shared subject-mode smoothing control rendered in
// both the Create recipe and the EditClipModal Reframe tab. Pins the partials it
// emits and the hold-row gating on the smooth toggle.
import { test, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SubjectSmoothControls, HOLD_OPTS, HOLD_DEFAULT } from './reframeControls.jsx';

test('smooth on: renders the hold segmented with a labelled default', () => {
  render(<SubjectSmoothControls smooth hold={HOLD_DEFAULT} onChange={vi.fn()} />);
  // Every 0.5s preset is present (Off .. 3.0s).
  for (const o of HOLD_OPTS) expect(screen.getByRole('button', { name: o.label })).toBeTruthy();
});

test('toggling the switch emits { subjectSmooth }', () => {
  const onChange = vi.fn();
  render(<SubjectSmoothControls smooth hold={45} onChange={onChange} />);
  fireEvent.click(screen.getByRole('switch'));
  expect(onChange).toHaveBeenCalledWith({ subjectSmooth: false });
});

test('choosing a hold preset emits { subjectHold } in frames', () => {
  const onChange = vi.fn();
  render(<SubjectSmoothControls smooth hold={45} onChange={onChange} />);
  fireEvent.click(screen.getByRole('button', { name: '3.0s' }));
  expect(onChange).toHaveBeenCalledWith({ subjectHold: 90 });
  fireEvent.click(screen.getByRole('button', { name: 'Off' }));
  expect(onChange).toHaveBeenCalledWith({ subjectHold: 0 });
});

test('smooth off: the hold row is hidden', () => {
  render(<SubjectSmoothControls smooth={false} hold={45} onChange={vi.fn()} />);
  expect(screen.queryByRole('button', { name: '1.5s' })).toBeNull();
});

test('undefined smooth defaults to on (control shows the hold row)', () => {
  render(<SubjectSmoothControls smooth={undefined} hold={undefined} onChange={vi.fn()} />);
  expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('true');
  // Unknown hold falls back to the default preset being selectable.
  expect(screen.getByRole('button', { name: '1.5s' })).toBeTruthy();
});
