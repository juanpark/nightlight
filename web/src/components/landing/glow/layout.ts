// The glow page's layouts, in one place for the code that needs them: the 3D
// scene (camera framing) and the callout line (shown only on the wide layout).
// Glow.module.css uses the same two queries for its phone and sideways blocks;
// change them together.

// Phone layout: upright phones, and phones on their side.
export const PHONE_QUERY = "(max-width: 820px), (max-height: 520px) and (orientation: landscape)";
// A phone on its side: short and wide.
export const SIDEWAYS_QUERY = "(max-height: 520px) and (orientation: landscape)";
