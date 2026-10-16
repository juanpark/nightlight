import type { ReactNode } from "react";
import { SculptedMascot } from "../../mascot/SculptedMascot";
import s from "./Day.module.css";

// A warm plaster room lit from inside while it is night outside: three arched
// windows onto a starry sky, moonlight on the floor, the sample home's machines
// resting on plinths and the mascot on the middle one with its star lit.
// Drawn in a 1600 x 1000 space; the page crops it. Each depth sits in its own
// layer (data-depth) so the page can move the camera with the pointer.

const VP: [number, number] = [800, 430]; // where the room's lines meet

type Win = { x: number; w: number; top: number; bottom: number };
const WINDOWS: Win[] = [
  { x: 150, w: 260, top: 190, bottom: 610 },
  { x: 580, w: 440, top: 96, bottom: 700 },
  { x: 1190, w: 260, top: 210, bottom: 690 },
];

function arch({ x, w, top, bottom }: Win) {
  const r = w / 2;
  return `M${x} ${bottom}V${top + r}A${r} ${r} 0 0 1 ${x + w} ${top + r}V${bottom}Z`;
}

// Moonlight through a window lands on the floor as a flattened, slanted copy of it.
const FLOOR_LIGHT = "matrix(1 0 -0.42 -0.2 380 950)";

function bars({ x, w, top, bottom }: Win) {
  const r = w / 2;
  const v = w > 300 ? [x + w / 4, x + w / 2, x + (3 * w) / 4] : [x + w / 2];
  const h = [top + r, bottom - 150];
  return (
    <>
      {v.map((bx) => (
        <line key={`v${bx}`} x1={bx} y1={top} x2={bx} y2={bottom} />
      ))}
      {h.map((by) => (
        <line key={`h${by}`} x1={x} y1={by} x2={x + w} y2={by} />
      ))}
    </>
  );
}

const back = ([x, y]: [number, number], k = 0.075): [number, number] => [x + (VP[0] - x) * k, y + (VP[1] - y) * k];
const pts = (p: [number, number][]) => p.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");

function Plinth({ x, w, top, bottom }: { x: number; w: number; top: number; bottom: number }) {
  const tl: [number, number] = [x, top];
  const tr: [number, number] = [x + w, top];
  const leftSide = x > VP[0]; // right of centre, so its left face shows
  const sx = leftSide ? x : x + w;
  const L = (bottom - top) * 0.5;
  return (
    <g>
      <polygon
        points={pts([
          [x + w * 0.15, bottom],
          [x + w, bottom],
          [x + w + L, bottom + L * 0.16],
          [x + w * 0.15 + L, bottom + L * 0.16],
        ])}
        fill="#5a3f27"
        opacity="0.22"
        filter="url(#dl-blur8)"
      />
      <polygon
        points={pts([[sx, top], [sx, bottom], back([sx, bottom]), back([sx, top])])}
        fill={leftSide ? "#efe4d4" : "#c8b49b"}
      />
      <polygon points={pts([tl, tr, back(tr), back(tl)])} fill="#f6eee2" />
      <rect x={x} y={top} width={w} height={bottom - top} fill="url(#dl-plinth)" />
      <rect x={x} y={top} width={w} height="2" fill="#fff8ec" opacity="0.8" />
      <rect x={x} y={bottom - 10} width={w} height="10" fill="url(#dl-ao)" />
    </g>
  );
}

// A machine as a small moulded block in the same plaster as the plinths: its
// front face softly rounded by light, the side and top it shows from this
// viewpoint, a contact shadow under it. Details go on the front via children.
function Block({
  x, y, w, h, r = 5, k = 0.032, anim = true, children,
}: { x: number; y: number; w: number; h: number; r?: number; k?: number; anim?: boolean; children?: ReactNode }) {
  const leftSide = x > VP[0];
  const sx = leftSide ? x : x + w;
  const showTop = y > VP[1];
  return (
    <g data-anim={anim ? "device" : undefined}>
      <ellipse cx={x + w / 2 + (leftSide ? 6 : -6)} cy={y + h} rx={w * 0.58} ry="5" fill="#4a3018" opacity="0.32" filter="url(#dl-blur3)" />
      <polygon
        points={pts([[sx, y + r], [sx, y + h], back([sx, y + h], k), back([sx, y + r], k)])}
        fill={leftSide ? "url(#dl-side)" : "#c4ae92"}
      />
      {showTop && <polygon points={pts([[x + r, y], [x + w - r, y], back([x + w - r, y], k), back([x + r, y], k)])} fill="#f7f0e5" />}
      <rect x={x} y={y} width={w} height={h} rx={r} fill="url(#dl-device)" filter="url(#dl-matte)" />
      <rect x={x + r} y={y + 0.5} width={w - 2 * r} height="1.4" rx="0.7" fill="#fffaf1" opacity="0.9" />
      <rect x={x + 2} y={y + h - 7} width={w - 4} height="7" rx="3" fill="url(#dl-ao)" />
      {children}
    </g>
  );
}

// A status light: a small lit bead with a soft halo.
function Led({ x, y, tone, blink }: { x: number; y: number; tone: "ok" | "warn"; blink?: boolean }) {
  return (
    <g data-anim="led">
      <g className={blink ? s.blink : undefined}>
        <circle cx={x} cy={y} r="9" fill={`url(#dl-led-${tone})`} />
        <circle cx={x} cy={y} r="2.6" fill={tone === "ok" ? "#5fae78" : "#eea21c"} />
        <circle cx={x - 0.7} cy={y - 0.8} r="0.9" fill="#fff" opacity="0.8" />
      </g>
    </g>
  );
}

// A recessed slot cut into a face: a shadowed inner edge on top, a lit lip below.
function Slot({ x, y, w, h, r = 2 }: { x: number; y: number; w: number; h: number; r?: number }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={r} fill="#b39d80" />
      <rect x={x} y={y} width={w} height={Math.min(3, h / 2)} rx={r} fill="#8d7559" opacity="0.6" />
      <rect x={x} y={y + h - 1} width={w} height="1" fill="#fff8ec" opacity="0.7" />
    </g>
  );
}

const STARS = [
  [170, 250, 1.6], [230, 330, 1.1], [300, 280, 1.4], [360, 380, 1], [210, 430, 1.2], [330, 470, 0.9],
  [620, 200, 1.3], [700, 150, 1], [760, 260, 1.6], [850, 190, 1.1], [930, 240, 1.4], [980, 330, 1],
  [650, 340, 0.9], [890, 400, 1.2], [720, 420, 0.8], [1230, 300, 1.2], [1300, 250, 0.9], [1420, 420, 1.1],
  [1250, 460, 1], [1400, 270, 0.8], [600, 470, 1], [1000, 470, 0.9],
];

const MOTES = [
  [700, 300, 2.2], [760, 420, 1.6], [880, 260, 1.8], [940, 520, 2.4], [1020, 380, 1.5], [650, 560, 1.7],
  [1110, 470, 2], [300, 420, 1.6], [360, 560, 2.1], [1290, 400, 1.7], [820, 640, 1.4], [1180, 620, 1.9],
];

export function DayScene() {
  return (
    <svg className={s.scene} viewBox="0 0 1600 1000" preserveAspectRatio="xMidYMax slice" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="dl-wall" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#d9cbb7" />
          <stop offset="0.5" stopColor="#e9dccb" />
          <stop offset="1" stopColor="#dccbb4" />
        </linearGradient>
        <radialGradient id="dl-lamp" cx="0.53" cy="0.42" r="0.62">
          <stop offset="0" stopColor="#fff1d2" stopOpacity="0.85" />
          <stop offset="0.5" stopColor="#fbe3b8" stopOpacity="0.3" />
          <stop offset="1" stopColor="#fbe3b8" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="dl-vignette" cx="0.5" cy="0.45" r="0.75">
          <stop offset="0.55" stopColor="#4a3420" stopOpacity="0" />
          <stop offset="1" stopColor="#4a3420" stopOpacity="0.28" />
        </radialGradient>
        <linearGradient id="dl-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#0c1229" />
          <stop offset="0.55" stopColor="#18223f" />
          <stop offset="1" stopColor="#2c3657" />
        </linearGradient>
        <radialGradient id="dl-cloud" cx="0.45" cy="0.2" r="0.8">
          <stop offset="0" stopColor="#4b577b" />
          <stop offset="0.55" stopColor="#2c365a" />
          <stop offset="1" stopColor="#1b2443" />
        </radialGradient>
        <radialGradient id="dl-moonhalo">
          <stop offset="0" stopColor="#e9ecf6" stopOpacity="0.35" />
          <stop offset="1" stopColor="#e9ecf6" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="dl-glassglow" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#ffd9a0" stopOpacity="0.14" />
          <stop offset="0.5" stopColor="#ffd9a0" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="dl-floor" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#caa87f" />
          <stop offset="1" stopColor="#ad8761" />
        </linearGradient>
        <radialGradient id="dl-floorglow" cx="0.5" cy="0.1" r="0.6">
          <stop offset="0" stopColor="#ffe2a8" stopOpacity="0.5" />
          <stop offset="1" stopColor="#ffe2a8" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="dl-plinth" x1="0" y1="0" x2="1" y2="0.3">
          <stop offset="0" stopColor="#efe4d4" />
          <stop offset="1" stopColor="#d6c4ab" />
        </linearGradient>
        <linearGradient id="dl-ao" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#5a3f27" stopOpacity="0" />
          <stop offset="1" stopColor="#5a3f27" stopOpacity="0.18" />
        </linearGradient>
        <linearGradient id="dl-reveal" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#cdbba3" />
          <stop offset="1" stopColor="#e4d5c1" />
        </linearGradient>
        <linearGradient id="dl-device" x1="0" y1="0" x2="1" y2="0.6">
          <stop offset="0" stopColor="#fbf4ea" />
          <stop offset="1" stopColor="#e1d1bb" />
        </linearGradient>
        <linearGradient id="dl-side" x1="1" y1="0" x2="0" y2="0">
          <stop offset="0" stopColor="#dccbb3" />
          <stop offset="1" stopColor="#c9b498" />
        </linearGradient>
        <radialGradient id="dl-led-ok">
          <stop offset="0" stopColor="#7fd197" stopOpacity="0.55" />
          <stop offset="1" stopColor="#7fd197" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="dl-led-warn">
          <stop offset="0" stopColor="#ffb733" stopOpacity="0.7" />
          <stop offset="1" stopColor="#ffb733" stopOpacity="0" />
        </radialGradient>
        {/* Soft moulded edges: the face's alpha, blurred, lit from the upper left like the mascot. */}
        <filter id="dl-matte" x="-10%" y="-10%" width="120%" height="120%" colorInterpolationFilters="sRGB">
          <feGaussianBlur in="SourceAlpha" stdDeviation="2.4" result="h" />
          <feDiffuseLighting in="h" surfaceScale="3.2" diffuseConstant="1.1" lightingColor="#fff" result="d">
            <feDistantLight azimuth="225" elevation="60" />
          </feDiffuseLighting>
          <feSpecularLighting in="h" surfaceScale="3.2" specularConstant="0.3" specularExponent="16" lightingColor="#fff4e0" result="sp">
            <feDistantLight azimuth="225" elevation="52" />
          </feSpecularLighting>
          <feComposite in="d" in2="SourceGraphic" operator="arithmetic" k1="1.04" result="lit" />
          <feComposite in="sp" in2="SourceAlpha" operator="in" result="sheen" />
          <feComposite in="lit" in2="sheen" operator="arithmetic" k2="1" k3="0.4" result="out" />
          <feComposite in="out" in2="SourceAlpha" operator="in" />
        </filter>
        <filter id="dl-blur3" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="3" />
        </filter>
        <filter id="dl-blur8" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="8" />
        </filter>
        <mask id="dl-crescent" maskUnits="userSpaceOnUse" x="1300" y="300" width="80" height="80">
          <circle cx="1338" cy="340" r="26" fill="#fff" />
          <circle cx="1350" cy="332" r="23" fill="#000" />
        </mask>
        <clipPath id="dl-glass">
          {WINDOWS.map((w) => (
            <path key={w.x} d={arch(w)} />
          ))}
        </clipPath>
        {WINDOWS.map((w) => (
          <mask key={w.x} id={`dl-pane-${w.x}`} maskUnits="userSpaceOnUse" x="0" y="0" width="1600" height="1000">
            <path d={arch(w)} fill="#fff" />
            <g stroke="#000" strokeWidth="14">{bars(w)}</g>
          </mask>
        ))}
      </defs>

      {/* Back wall with its windows. The night outside moves a little against the frames. */}
      <g data-depth="wall">
        <rect x="-60" y="-40" width="1720" height="840" fill="url(#dl-wall)" />
        <rect x="-60" y="-40" width="1720" height="840" fill="url(#dl-lamp)" data-anim="light" />
        <rect x="-60" y="0" width="1720" height="46" fill="#d6c7b1" />
        <rect x="-60" y="46" width="1720" height="3" fill="#f3e9da" />
        <rect x="-60" y="52" width="1720" height="8" fill="#cfbea6" opacity="0.7" />
        {[470, 1100].map((x) => (
          <g key={x}>
            <rect x={x} y="60" width="40" height="710" fill="#ece0cf" />
            <rect x={x + 40} y="60" width="10" height="710" fill="#d2c0a7" opacity="0.8" />
          </g>
        ))}

        {WINDOWS.map((w) => (
          <path key={w.x} d={arch({ ...w, x: w.x - 16, w: w.w + 32, top: w.top - 16 })} fill="url(#dl-reveal)" />
        ))}
        <g clipPath="url(#dl-glass)">
          <g data-depth="sky">
            <rect x="0" y="40" width="1600" height="720" fill="url(#dl-sky)" />
            <g fill="#f4f1e8" className={s.stars}>
              {STARS.map(([x, y, r], i) => (
                <circle key={i} cx={x} cy={y} r={r} style={{ animationDelay: `${(i % 6) * 0.8}s` }} />
              ))}
            </g>
            <circle cx="1338" cy="340" r="70" fill="url(#dl-moonhalo)" />
            <circle cx="1338" cy="340" r="26" fill="#f1ede2" mask="url(#dl-crescent)" />
            <g className={s.clouds}>
              <Cloud x={120} y={520} k={1.1} />
              <Cloud x={820} y={520} k={1.4} />
              <Cloud x={1250} y={560} k={1.1} />
            </g>
            <path
              d="M0 640C120 600 230 618 340 600C470 580 560 630 700 612C860 592 960 560 1100 590C1240 620 1360 585 1600 610V760H0Z"
              fill="#111830"
            />
            {[[260, 640], [292, 636], [760, 622], [778, 626], [1040, 600], [1300, 628], [1318, 624]].map(([x, y]) => (
              <rect key={`${x}`} x={x} y={y} width="5" height="4" fill="#f4c46a" opacity="0.9" />
            ))}
          </g>
          <rect x="0" y="40" width="1600" height="720" fill="url(#dl-glassglow)" />
        </g>
        <g fill="none" stroke="#8f6b48" strokeLinecap="square">
          {WINDOWS.map((w) => (
            <g key={w.x}>
              <path d={arch(w)} strokeWidth="11" />
              <g strokeWidth="7" clipPath="url(#dl-glass)">
                {bars(w)}
              </g>
            </g>
          ))}
        </g>
        {WINDOWS.map((w) => (
          <g key={w.x}>
            <rect x={w.x - 26} y={w.bottom} width={w.w + 52} height="12" fill="#f3e9da" />
            <rect x={w.x - 26} y={w.bottom + 12} width={w.w + 52} height="6" fill="#cbb79c" />
          </g>
        ))}

        {/* Router on a small wall shelf */}
        <g>
          <ellipse cx="522" cy="456" rx="54" ry="5" fill="#5a3f27" opacity="0.22" filter="url(#dl-blur3)" />
          <rect x="470" y="440" width="104" height="10" fill="#f2e8da" />
          <rect x="470" y="450" width="104" height="4" fill="#c8b49b" />
          <path d="M488 454 L504 472 L509 454Z" fill="#d6c5ae" />
          <path d="M556 454 L540 472 L535 454Z" fill="#d6c5ae" />
          <g data-anim="device">
          <g filter="url(#dl-matte)">
            <rect x="497" y="370" width="7" height="48" rx="3.5" fill="#efe5d6" transform="rotate(-9 500 416)" />
            <rect x="540" y="370" width="7" height="48" rx="3.5" fill="#e2d4c0" transform="rotate(9 543 416)" />
          </g>
          <Block x={484} y={408} w={76} h={32} r={7} k={0.028} anim={false}>
            <Slot x={516} y={419} w={34} h={3} r={1.5} />
            <Slot x={516} y={426} w={34} h={3} r={1.5} />
            <Led x={497} y={424} tone="ok" />
          </Block>
          </g>
        </g>
      </g>

      {/* Floor, with cool moonlight lying across the warm boards */}
      <g data-depth="floor">
        <rect x="-60" y="770" width="1720" height="24" fill="#efe4d4" />
        <rect x="-60" y="792" width="1720" height="3" fill="#c8b49b" />
        <rect x="-60" y="795" width="1720" height="245" fill="url(#dl-floor)" />
        <rect x="-60" y="795" width="1720" height="245" fill="url(#dl-floorglow)" data-anim="light" />
        <g stroke="#94704c" strokeOpacity="0.45" strokeWidth="1.2">
          {Array.from({ length: 37 }, (_, i) => {
            const xb = -1000 + i * 100;
            const xt = VP[0] + ((xb - VP[0]) * (795 - VP[1])) / (1000 - VP[1]);
            return <line key={i} x1={xt} y1="795" x2={xb} y2="1040" />;
          })}
          {[812, 834, 862, 898, 944].map((y) => (
            <line key={y} x1="-60" y1={y} x2="1660" y2={y} strokeOpacity="0.25" />
          ))}
        </g>
        <g transform={FLOOR_LIGHT} filter="url(#dl-blur3)" style={{ mixBlendMode: "screen" }}>
          {WINDOWS.map((w) => (
            <rect key={w.x} x="0" y="0" width="1600" height="1000" fill="#9fb2d6" opacity="0.28" mask={`url(#dl-pane-${w.x})`} />
          ))}
        </g>
      </g>

      {/* The sample home's machines, resting on plinths */}
      <g data-depth="back">
        <Plinth x={1080} w={150} top={650} bottom={884} />
        {/* Raspberry Pi: a small vented case; its amber light asks for a look. */}
        <Block x={1098} y={600} w={124} h={50} r={8}>
          {[1112, 1124, 1136, 1148, 1160].map((x) => (
            <Slot key={x} x={x} y={612} w={6} h={26} r={3} />
          ))}
          <Slot x={1178} y={616} w={16} h={10} r={2} />
          <Slot x={1178} y={630} w={16} h={8} r={2} />
          <Led x={1206} y={622} tone="warn" blink />
        </Block>

        {/* NAS: a tall block with four drive bays */}
        <Plinth x={1300} w={160} top={596} bottom={862} />
        <Block x={1326} y={474} w={110} h={122} r={9}>
          {[1340, 1363, 1386, 1409].map((x) => (
            <g key={x}>
              <Slot x={x} y={490} w={15} h={78} r={4} />
              <rect x={x + 5} y={498} width="5" height="2" rx="1" fill="#f5ecdf" opacity="0.8" />
            </g>
          ))}
          <Led x={1344} y={582} tone="ok" />
          <Led x={1356} y={582} tone="ok" />
        </Block>

        {/* Mac mini on a side table */}
        <g>
          <polygon points="1500,880 1600,880 1640,900 1540,900" fill="#5a3f27" opacity="0.2" filter="url(#dl-blur8)" />
          <rect x="1490" y="690" width="12" height="190" fill="#85623f" />
          <rect x="1580" y="690" width="12" height="190" fill="#745536" />
          <polygon points="1470,690 1640,690 1630,676 1478,676" fill="#aa835b" />
          <rect x="1470" y="690" width="170" height="10" fill="#85623f" />
          <rect x="1470" y="690" width="170" height="1.5" fill="#c9a67c" opacity="0.8" />
          <Block x={1504} y={650} w={100} h={30} r={10} k={0.028}>
            <Slot x={1520} y={666} w={30} h={3} r={1.5} />
            <Led x={1590} y={667} tone="ok" />
          </Block>
        </g>
      </g>

      {/* The mascot on the middle plinth: the still point the camera turns around */}
      <g>
        <Plinth x={610} w={380} top={770} bottom={935} />
        <g transform="translate(640 292) scale(2)">
          <g className={s.mascot}>
            <SculptedMascot id="dl-m" />
          </g>
        </g>
      </g>

      <rect x="-60" y="-40" width="1720" height="1080" fill="url(#dl-vignette)" pointerEvents="none" />

      <g data-depth="air" fill="#fff6e2" className={s.motes}>
        {MOTES.map(([x, y, r], i) => (
          <circle key={i} cx={x} cy={y} r={r} opacity="0.8" style={{ animationDelay: `${-i * 1.7}s` }} />
        ))}
      </g>
    </svg>
  );
}

function Cloud({ x, y, k }: { x: number; y: number; k: number }) {
  const puffs: [number, number, number][] = [
    [0, 40, 62], [70, 10, 78], [150, 30, 66], [215, 52, 48], [-60, 62, 44], [100, 66, 70],
  ];
  return (
    <g transform={`translate(${x} ${y}) scale(${k})`} opacity="0.85">
      {puffs.map(([cx, cy, r], i) => (
        <circle key={i} cx={cx} cy={cy} r={r} fill="url(#dl-cloud)" />
      ))}
    </g>
  );
}
