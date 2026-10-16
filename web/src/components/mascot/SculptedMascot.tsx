import { BODY, EYES, FACE, STAR, STRING } from "./shapes";

// The traced mascot rendered as a matte vinyl figure in daylight: the same
// shapes as Mascot, given volume by soft light from the upper left instead of
// flat fills. Returns a <g> in the artwork's 193 x 243 space, so a scene can
// place it with a transform. `id` keeps the filter ids unique per instance.
export function SculptedMascot({ id, className }: { id: string; className?: string }) {
  const vinyl = `${id}-vinyl`;
  const mask = `${id}-mask`;
  const balloon = `${id}-balloon`;
  const inset = `${id}-inset`;
  const soft = `${id}-soft`;

  return (
    <g className={className}>
      <defs>
        {/* Puffy matte body: blurred alpha as a height map, lit and multiplied over the fill. */}
        <filter id={vinyl} x="-10%" y="-10%" width="120%" height="120%" colorInterpolationFilters="sRGB">
          <feGaussianBlur in="SourceAlpha" stdDeviation="7" result="h" />
          <feDiffuseLighting in="h" surfaceScale="11" diffuseConstant="1.18" lightingColor="#fff" result="d">
            <feDistantLight azimuth="225" elevation="48" />
          </feDiffuseLighting>
          <feSpecularLighting in="h" surfaceScale="11" specularConstant="0.62" specularExponent="11" lightingColor="#fff6e6" result="s">
            <feDistantLight azimuth="222" elevation="40" />
          </feSpecularLighting>
          <feComposite in="d" in2="SourceGraphic" operator="arithmetic" k1="1.15" result="lit" />
          <feComposite in="s" in2="SourceAlpha" operator="in" result="sheen" />
          <feComposite in="lit" in2="sheen" operator="arithmetic" k2="1" k3="0.42" result="out" />
          <feComposite in="out" in2="SourceAlpha" operator="in" />
        </filter>
        <filter id={mask} x="-10%" y="-10%" width="120%" height="120%" colorInterpolationFilters="sRGB">
          <feGaussianBlur in="SourceAlpha" stdDeviation="3.2" result="h" />
          <feDiffuseLighting in="h" surfaceScale="5" diffuseConstant="1.08" lightingColor="#fff" result="d">
            <feDistantLight azimuth="225" elevation="56" />
          </feDiffuseLighting>
          <feSpecularLighting in="h" surfaceScale="5" specularConstant="0.35" specularExponent="18" lightingColor="#fff" result="s">
            <feDistantLight azimuth="225" elevation="50" />
          </feSpecularLighting>
          <feComposite in="d" in2="SourceGraphic" operator="arithmetic" k1="1.02" result="lit" />
          <feComposite in="s" in2="SourceAlpha" operator="in" result="sheen" />
          <feComposite in="lit" in2="sheen" operator="arithmetic" k2="1" k3="0.5" result="out" />
          <feComposite in="out" in2="SourceAlpha" operator="in" />
        </filter>
        <filter id={balloon} x="-10%" y="-10%" width="120%" height="120%" colorInterpolationFilters="sRGB">
          <feGaussianBlur in="SourceAlpha" stdDeviation="6" result="h" />
          <feDiffuseLighting in="h" surfaceScale="10" diffuseConstant="1.1" lightingColor="#fff" result="d">
            <feDistantLight azimuth="225" elevation="50" />
          </feDiffuseLighting>
          <feSpecularLighting in="h" surfaceScale="10" specularConstant="0.85" specularExponent="22" lightingColor="#fffaf0" result="s">
            <feDistantLight azimuth="225" elevation="46" />
          </feSpecularLighting>
          <feComposite in="d" in2="SourceGraphic" operator="arithmetic" k1="1.06" result="lit" />
          <feComposite in="s" in2="SourceAlpha" operator="in" result="sheen" />
          <feComposite in="lit" in2="sheen" operator="arithmetic" k2="1" k3="0.55" result="out" />
          <feComposite in="out" in2="SourceAlpha" operator="in" />
        </filter>
        {/* The mask sits slightly into the body: a soft occlusion line around it. */}
        <filter id={inset} x="-10%" y="-10%" width="120%" height="120%">
          <feGaussianBlur stdDeviation="1.6" />
        </filter>
        <filter id={soft} x="-30%" y="-200%" width="160%" height="500%">
          <feGaussianBlur stdDeviation="4" />
        </filter>
      </defs>

      {/* Contact shadow, falling away from the window light. */}
      <ellipse cx="86" cy="236" rx="70" ry="6" fill="#4a3826" opacity="0.38" filter={`url(#${soft})`} />
      <ellipse cx="80" cy="235.5" rx="52" ry="2.6" fill="#2a2016" opacity="0.5" filter={`url(#${inset})`} />

      <g data-part="balloon">
        <path d={STRING} fill="#5b5148" />
        <path d={STAR} fill="#efc544" filter={`url(#${balloon})`} />
      </g>

      <g data-part="body">
        <path d={BODY} fill="#3a3836" filter={`url(#${vinyl})`} />
        <path d="M34.3 192C35.4 201 33.4 210.6 25 215.8C30.6 209.6 32.6 201.4 34.3 192Z" fill="#1c1b1a" opacity="0.55" />
        <path d="M130.8 155C129.6 163 131 176 136.5 182.5" fill="none" stroke="#1c1b1a" strokeOpacity="0.5" strokeWidth="1" strokeLinecap="round" />
        <path d={FACE} fill="none" stroke="#141312" strokeWidth="3" opacity="0.55" filter={`url(#${inset})`} transform="translate(0.8 1.2)" />
        <path d={FACE} fill="#efe9df" filter={`url(#${mask})`} />
        <g data-part="eyes">
          {EYES.map((d) => (
            <path key={d} d={d} fill="#1b1a19" />
          ))}
          {/* A small gloss on each eye from the window. */}
          <ellipse cx="112.6" cy="140.6" rx="1.5" ry="2.1" fill="#fff" opacity="0.75" transform="rotate(-18 112.6 140.6)" />
          <ellipse cx="51.6" cy="151.6" rx="1.5" ry="2.1" fill="#fff" opacity="0.75" transform="rotate(-18 51.6 151.6)" />
        </g>
      </g>
    </g>
  );
}
