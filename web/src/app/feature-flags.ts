// Compile-time defaults for UI feature flags, shared by the heavy app and
// Lite. Flip a default here, or override per browser without a rebuild:
//   localStorage.setItem('mimb:flag:blogRollDropdown', 'false')
export const FEATURE_FLAG_DEFAULTS = {
  // Blog roll category filters render as a compact dropdown instead of a
  // stack of buttons.
  blogRollDropdown: true,
} as const;

export type FeatureFlagName = keyof typeof FEATURE_FLAG_DEFAULTS;

export function featureFlag(name: FeatureFlagName): boolean {
  try {
    const override = localStorage.getItem(`mimb:flag:${name}`);
    if (override === 'true') return true;
    if (override === 'false') return false;
  } catch {
    // Storage disabled (private mode etc.) — fall through to the default.
  }
  return FEATURE_FLAG_DEFAULTS[name];
}
