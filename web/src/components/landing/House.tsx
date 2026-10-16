import type { ReactNode } from "react";
import { Mascot } from "../mascot/Mascot";
import { MascotPose } from "../mascot/MascotPose";
import type { PoseName } from "../mascot/poses";
import s from "./House.module.css";

// The sample home as a cutaway at night: attic, two floors and a garage.
// Flat fills only. Devices sit in the rooms; each has an unlit and a lit layer
// (warm pool, status light, bright label) that the stage switches with CSS.

export type DeviceId = "pi" | "pc" | "nas" | "mac" | "router" | "cam";

type Dev = {
  id: DeviceId;
  label: string;
  room: string;
  dot: [number, number];
  pool: [number, number];
  text: [number, number];
};

const DEVICES: Dev[] = [
  { id: "pi", label: "Raspberry Pi", room: "attic", dot: [596, 333], pool: [568, 330], text: [568, 312] },
  { id: "pc", label: "Minecraft server", room: "upper", dot: [458, 466], pool: [420, 470], text: [420, 424] },
  { id: "nas", label: "NAS", room: "upper", dot: [770, 452], pool: [738, 470], text: [738, 428] },
  { id: "mac", label: "Mac Mini", room: "ground", dot: [448, 662], pool: [422, 640], text: [425, 566] },
  { id: "router", label: "Router", room: "ground", dot: [800, 618], pool: [770, 620], text: [770, 584] },
  { id: "cam", label: "Camera recorder", room: "garage", dot: [920, 630], pool: [890, 636], text: [895, 606] },
];

// Feet position of each pose in its own viewBox, so a mascot can stand on a floor.
const FEET: Record<PoseName | "idle", [number, number, number]> = {
  // [x, y, viewBox size]
  idle: [76, 234.3, 193],
  wave: [131.5, 233.5, 256],
  walk: [118, 232.5, 256],
  sit: [103.5, 239.5, 256],
  peek: [117, 214, 256],
  happy: [121.5, 211.5, 256],
  wiggle: [109.5, 216.5, 256],
};

function Stand({
  pose,
  size,
  at,
  className,
  thinking,
}: {
  pose: PoseName | "idle";
  size: number;
  at: [number, number];
  className?: string;
  thinking?: boolean;
}) {
  const [fx, fy, vb] = FEET[pose];
  const k = size / vb;
  return (
    <g transform={`translate(${at[0] - fx * k} ${at[1] - fy * k})`}>
      <g className={className}>
        {pose === "idle" ? (
          <Mascot size={size} mood={thinking ? "thinking" : "idle"} />
        ) : (
          <MascotPose pose={pose} size={size} />
        )}
      </g>
    </g>
  );
}

function Room({ id, d, children }: { id: string; d: string; children?: ReactNode }) {
  const pools = (room: string) =>
    DEVICES.filter((v) => v.room === room).map((v) => (
      <ellipse
        key={v.id}
        className={`${s.lit} ${s[`dev_${v.id}`]}`}
        cx={v.pool[0]}
        cy={v.pool[1]}
        rx="104"
        ry="84"
        fill="url(#nl-pool)"
      />
    ));
  return (
    <g>
      <clipPath id={`nl-room-${id}`}>
        <path d={d} />
      </clipPath>
      <path d={d} className={s.room} />
      <g clipPath={`url(#nl-room-${id})`}>
        {children}
        {pools(id)}
      </g>
    </g>
  );
}

const ATTIC = "M150 372L470 162L790 372Z";
const UPPER = "M122 396H818V524H122Z";
const GROUND = "M122 536H818V700H122Z";
const GARAGE = "M842 584H948V700H842Z";

export function House({ viewBox }: { viewBox: string }) {
  return (
    <svg
      className={s.scene}
      viewBox={viewBox}
      preserveAspectRatio="xMaxYMax meet"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <radialGradient id="nl-pool">
          <stop offset="0" stopColor="#fdd83a" stopOpacity="0.3" />
          <stop offset="0.5" stopColor="#fdd83a" stopOpacity="0.09" />
          <stop offset="1" stopColor="#fdd83a" stopOpacity="0" />
        </radialGradient>
      </defs>

      <g className={s.camera}>
        {/* Land: far hills, drifting fog, near ground, trees. */}
        <path
          className={s.hillFar}
          d="M-2400 560C-1900 470-1500 520-1150 500S-620 430-300 480S200 440 520 470S1100 420 1500 470S2300 520 3400 480V800H-2400Z"
        />
        <ellipse className={`${s.fog} ${s.fogA}`} cx="-120" cy="600" rx="760" ry="34" />
        <path
          className={s.hillNear}
          d="M-2400 640C-2000 600-1600 640-1200 620S-500 580-150 630S500 650 1000 640S2000 610 3400 640V800H-2400Z"
        />
        <ellipse className={`${s.fog} ${s.fogB}`} cx="1180" cy="660" rx="520" ry="26" />
        <rect className={s.ground} x="-2400" y="700" width="5800" height="400" />
        <g className={s.tree}>
          <path d="M-60 700V610" strokeWidth="10" />
          <circle cx="-60" cy="590" r="46" />
          <circle cx="-96" cy="626" r="34" />
          <circle cx="-26" cy="622" r="38" />
          <path d="M-330 700V640" strokeWidth="8" />
          <circle cx="-330" cy="626" r="32" />
          <circle cx="-352" cy="650" r="24" />
          <path d="M1040 700V630" strokeWidth="8" />
          <circle cx="1040" cy="612" r="36" />
          <circle cx="1066" cy="640" r="28" />
        </g>

        {/* Structure */}
        <path className={s.shell} d="M70 386L470 118L870 386Z" />
        <rect className={s.shell} x="110" y="384" width="720" height="316" />
        <rect className={s.shell} x="830" y="572" width="130" height="128" />
        <path className={s.eave} d="M60 390L470 115L880 390" />
        <path className={s.eave} d="M824 572H966" />
        <rect className={s.chimney} x="664" y="170" width="44" height="90" />

        {/* Attic */}
        <Room id="attic" d={ATTIC}>
          <circle className={s.window} cx="470" cy="232" r="22" />
          <path className={s.frame} d="M448 232H492M470 210V254" />
          <rect className={s.furn} x="236" y="330" width="46" height="42" rx="3" />
          <rect className={s.furn2} x="270" y="346" width="40" height="26" rx="3" />
          <rect className={s.furn} x="520" y="346" width="96" height="6" rx="2" />
          <rect className={s.furn} x="528" y="352" width="5" height="20" />
          <rect className={s.furn} x="603" y="352" width="5" height="20" />
          {/* Raspberry Pi: a small green board with a cable */}
          <rect className={s.pi} x="546" y="334" width="44" height="12" rx="2" />
          <rect className={s.chip} x="556" y="337" width="10" height="6" rx="1" />
          <path className={s.cable} d="M590 342C606 342 612 356 640 372" />
        </Room>

        {/* Upper floor: kids' room and study, a doorway between */}
        <Room id="upper" d={UPPER}>
          <rect className={s.window} x="270" y="420" width="58" height="44" rx="2" />
          <path className={s.frame} d="M299 420V464M270 442H328" />
          <circle className={s.winStar} cx="314" cy="430" r="2.4" />
          {/* bed */}
          <rect className={s.furn2} x="140" y="492" width="120" height="32" rx="6" />
          <rect className={s.furn} x="140" y="476" width="12" height="48" rx="3" />
          <rect className={s.pillow} x="156" y="484" width="34" height="11" rx="5" />
          {/* desk, monitor with a grass block, the server tower */}
          <rect className={s.furn} x="344" y="488" width="88" height="6" rx="2" />
          <rect className={s.furn} x="350" y="494" width="5" height="30" />
          <rect className={s.screen} x="360" y="452" width="54" height="32" rx="3" />
          <rect className={s.grass} x="380" y="461" width="14" height="5" />
          <rect className={s.dirt} x="380" y="466" width="14" height="9" />
          <rect className={s.furn} x="384" y="484" width="6" height="4" />
          <rect className={s.device} x="438" y="470" width="28" height="54" rx="3" />
          <path className={s.vent} d="M445 482H459M445 488H459M445 494H459" />
          {/* wall between rooms, open below */}
          <rect className={s.shell} x="468" y="396" width="12" height="44" />
          {/* study: shelf with books, desk lamp, the NAS */}
          <rect className={s.window} x="540" y="420" width="50" height="40" rx="2" />
          <path className={s.frame} d="M565 420V460M540 440H590" />
          <rect className={s.furn} x="520" y="490" width="110" height="6" rx="2" />
          <rect className={s.furn} x="526" y="496" width="5" height="28" />
          <rect className={s.furn} x="618" y="496" width="5" height="28" />
          <path className={s.lampArm} d="M540 490L552 470L572 476" />
          <path className={s.furn2} d="M566 470L584 476L578 486Z" />
          <rect className={s.furn} x="686" y="498" width="118" height="5" rx="1" />
          <rect className={s.book} x="690" y="474" width="7" height="24" />
          <rect className={s.book2} x="698" y="478" width="6" height="20" />
          <rect className={s.device} x="712" y="456" width="54" height="42" rx="4" />
          <path className={s.vent} d="M722 466V488M733 466V488M744 466V488M755 466V488" />
        </Room>

        {/* Ground floor: living room and hallway with stairs */}
        <Room id="ground" d={GROUND}>
          <rect className={s.window} x="176" y="562" width="72" height="50" rx="2" />
          <path className={s.frame} d="M212 562V612M176 587H248" />
          <circle className={s.winStar} cx="232" cy="572" r="2.4" />
          {/* sofa and floor lamp */}
          <rect className={s.furn2} x="150" y="630" width="140" height="34" rx="9" />
          <rect className={s.furn} x="142" y="656" width="156" height="44" rx="9" />
          <path className={s.lampArm} d="M318 700V604" />
          <path className={s.furn2} d="M302 604H334L326 586H310Z" />
          {/* TV, stand, the Mac Mini */}
          <rect className={s.screen} x="368" y="590" width="114" height="62" rx="4" />
          <rect className={s.furn} x="372" y="670" width="106" height="30" rx="3" />
          <rect className={s.device} x="398" y="660" width="48" height="10" rx="3" />
          {/* wall between rooms, open below */}
          <rect className={s.shell} x="520" y="536" width="12" height="42" />
          {/* stairs up */}
          <path className={s.stairs} d="M548 700V682H568V664H588V646H608V628H628V610H648V592H668V574H688V556H708V538H718V700Z" />
          {/* router on a wall shelf */}
          <rect className={s.furn} x="740" y="632" width="64" height="4" rx="1" />
          <rect className={s.device} x="748" y="618" width="46" height="14" rx="3" />
          <path className={s.antenna} d="M756 618L750 598M786 618L792 598" />
        </Room>

        {/* Garage: the camera recorder on a shelf, a camera outside */}
        <Room id="garage" d={GARAGE}>
          <rect className={s.furn} x="852" y="646" width="86" height="4" rx="1" />
          <rect className={s.device} x="866" y="626" width="52" height="20" rx="2" />
          <path className={s.vent} d="M874 636H894" />
        </Room>
        <path className={s.camera_} d="M960 594H976V604H960Z" />
        <path className={s.camera_} d="M976 597L984 594V604L976 601Z" />

        {/* Status lights and labels: unlit, then lit on top. */}
        {DEVICES.map((d) => (
          <g key={d.id} className={s.marker} data-device={d.id}>
            <circle className={s.dotOff} cx={d.dot[0]} cy={d.dot[1]} r="3.6" />
            <text className={s.labelOff} x={d.text[0]} y={d.text[1]}>
              {d.label}
            </text>
            <g className={`${s.lit} ${s[`dev_${d.id}`]}`}>
              <circle className={s.dotHalo} cx={d.dot[0]} cy={d.dot[1]} r="11" />
              <circle className={s.dotOn} cx={d.dot[0]} cy={d.dot[1]} r="3.6" />
              <text className={s.labelOn} x={d.text[0]} y={d.text[1]}>
                {d.label}
              </text>
            </g>
          </g>
        ))}

        {/* The night round (hero): floor by floor, then a rest by the Pi. */}
        <g className={s.round}>
          <Stand pose="walk" size={118} at={[150, 700]} className={s.walkGround} />
          <Stand pose="walk" size={110} at={[150, 524]} className={s.walkUpper} />
          <Stand pose="walk" size={104} at={[300, 372]} className={s.walkAttic} />
          <Stand pose="idle" size={88} at={[490, 372]} className={s.restAttic} />
        </g>
        <g className={s.still}>
          <Stand pose="idle" size={96} at={[620, 700]} />
        </g>

        {/* The story, in the attic beside the Pi. */}
        <g className={s.cast}>
          <Stand pose="peek" size={150} at={[462, 372]} className={s.asPeek} />
          <Stand pose="idle" size={100} at={[478, 372]} className={s.asThink} thinking />
          <Stand pose="wave" size={132} at={[478, 372]} className={s.asAsk} />
          <Stand pose="happy" size={132} at={[478, 372]} className={s.asHappy} />
          <Stand pose="sit" size={132} at={[468, 372]} className={s.asSit} />
        </g>
      </g>
    </svg>
  );
}
