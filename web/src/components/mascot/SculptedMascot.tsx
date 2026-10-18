import { BODY, EYES, FACE, STAR } from "./shapes";

// The traced mascot rendered as a matte vinyl figure: the same shapes as
// Mascot, given volume by soft light from the upper left instead of flat fills.
// The star is a smooth glowing foil balloon. Returns a <g> in the artwork's
// 193 x 243 space so a scene can place it with a transform. data-part hooks
// ("balloon", "glow", "face", "eyes") let a page move or light the parts.
export function SculptedMascot({ id, className }: { id: string; className?: string }) {
  const vinyl = `${id}-vinyl`;
  const mask = `${id}-mask`;
  const inset = `${id}-inset`;
  const soft = `${id}-soft`;
  const foil = `${id}-foil`;
  const glow = `${id}-glow`;
  const starClip = `${id}-star`;

  return (
    <g className={className}>
      <defs>
        {/* Puffy matte body: blurred alpha as a height map, lit and multiplied over the fill. */}
        <filter id={vinyl} x="-10%" y="-10%" width="120%" height="120%" colorInterpolationFilters="sRGB">
          <feGaussianBlur in="SourceAlpha" stdDeviation="7" result="h" />
          <feDiffuseLighting in="h" surfaceScale="11" diffuseConstant="1.18" lightingColor="#fff" result="d">
            <feDistantLight azimuth="225" elevation="48" />
          </feDiffuseLighting>
          <feSpecularLighting in="h" surfaceScale="11" specularConstant="0.62" specularExponent="11" lightingColor="#fff1d6" result="s">
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
        <filter id={inset} x="-10%" y="-10%" width="120%" height="120%">
          <feGaussianBlur stdDeviation="1.6" />
        </filter>
        <filter id={soft} x="-50%" y="-200%" width="200%" height="500%">
          <feGaussianBlur stdDeviation="4" />
        </filter>
        <radialGradient id={foil} cx="0.36" cy="0.3" r="0.8">
          <stop offset="0" stopColor="#fff6c4" />
          <stop offset="0.3" stopColor="#ffdf5e" />
          <stop offset="0.72" stopColor="#f2b928" />
          <stop offset="1" stopColor="#c98a12" />
        </radialGradient>
        <radialGradient id={glow}>
          <stop offset="0" stopColor="#ffd75a" stopOpacity="0.55" />
          <stop offset="0.45" stopColor="#ffc93a" stopOpacity="0.16" />
          <stop offset="1" stopColor="#ffc93a" stopOpacity="0" />
        </radialGradient>
        <clipPath id={starClip}>
          <path d={STAR} />
        </clipPath>
      </defs>

      {/* Contact shadow on the plinth. */}
      <ellipse cx="86" cy="236" rx="70" ry="6" fill="#3d2c1c" opacity="0.4" filter={`url(#${soft})`} />
      <ellipse cx="80" cy="235.5" rx="52" ry="2.6" fill="#22180f" opacity="0.5" filter={`url(#${inset})`} />

      <g data-part="balloon">
        <circle data-part="glow" cx="145" cy="44" r="92" fill={`url(#${glow})`} />
        <path d="M139.2 146C140.6 126 144.6 104 145.4 83" fill="none" stroke="#5b5148" strokeWidth="1.1" strokeLinecap="round" />
        <path d={STAR} fill={`url(#${foil})`} />
        <g clipPath={`url(#${starClip})`}>
          {/* Seam darkening at the edges, then the soft shine on the upper-left lobes. */}
          <path d={STAR} fill="none" stroke="#a8700a" strokeWidth="9" opacity="0.45" filter={`url(#${inset})`} />
          <ellipse cx="128" cy="38" rx="17" ry="7" fill="#fffbe6" opacity="0.75" transform="rotate(-24 128 38)" filter={`url(#${inset})`} />
          <ellipse cx="143" cy="20" rx="4" ry="8" fill="#fffbe6" opacity="0.6" transform="rotate(18 143 20)" filter={`url(#${inset})`} />
        </g>
        <ellipse cx="145.6" cy="82.4" rx="2.4" ry="1.6" fill="#c98a12" />
      </g>

      <g data-part="body">
        <path d={BODY} fill="#3a3836" filter={`url(#${vinyl})`} />
        <path d="M34.3 192C35.4 201 33.4 210.6 25 215.8C30.6 209.6 32.6 201.4 34.3 192Z" fill="#1c1b1a" opacity="0.55" />
        <path d="M130.8 155C129.6 163 131 176 136.5 182.5" fill="none" stroke="#1c1b1a" strokeOpacity="0.5" strokeWidth="1" strokeLinecap="round" />
        <g data-part="face">
          <path d={FACE} fill="none" stroke="#141312" strokeWidth="3" opacity="0.55" filter={`url(#${inset})`} transform="translate(0.8 1.2)" />
          <path d={FACE} fill="#efe9df" filter={`url(#${mask})`} />
          <g data-part="eyes">
            {EYES.map((d) => (
              <path key={d} data-part="eye" d={d} fill="#1b1a19" />
            ))}
          </g>
        </g>
      </g>
    </g>
  );
}
