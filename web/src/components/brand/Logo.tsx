import { useId } from "react";
import { BODY, EYES, FACE } from "../mascot/shapes";

// "nightlight" set in Funnel Display (heavy "night", thin "light"), converted to
// outlines so it never depends on the font loading. The dot on the second i is
// the light. Word colour follows `color`; the light uses --logo-light.
const VIEWBOX = "-40 -1230 5414 1530";
const NIGHT = "M110 0V-420H20V-600H204V-500H246Q282 -552 334 -582Q387 -611 469 -611Q597 -611 666 -542Q734 -473 734 -357V0H550V-321Q550 -383 518 -415Q485 -447 422 -447Q359 -447 326 -415Q294 -383 294 -321V0ZM829 0V-600H1013V0ZM921 -651Q880 -651 851 -680Q822 -709 822 -750Q822 -791 851 -820Q880 -849 921 -849Q962 -849 991 -820Q1020 -791 1020 -750Q1020 -709 991 -680Q962 -651 921 -651ZM1411 252Q1272 252 1186 196Q1099 141 1083 42H1277Q1300 108 1404 108Q1477 108 1516 75Q1554 42 1554 -19V-94H1549Q1521 -47 1476 -24Q1430 0 1365 0Q1281 0 1218 -38Q1156 -75 1122 -144Q1087 -213 1087 -306Q1087 -446 1164 -529Q1242 -612 1379 -612Q1455 -612 1510 -582Q1564 -553 1596 -500H1638V-600H1822V-420H1732V-19Q1732 111 1649 182Q1566 252 1411 252ZM1411 -160Q1476 -160 1512 -195Q1548 -230 1548 -292V-322Q1548 -383 1512 -418Q1475 -452 1411 -452Q1344 -452 1308 -414Q1271 -375 1271 -305Q1271 -235 1308 -198Q1344 -160 1411 -160ZM1878 0V-840H2062V-518H2066Q2095 -564 2142 -588Q2190 -611 2257 -611Q2370 -611 2436 -542Q2502 -473 2502 -357V0H2318V-321Q2318 -383 2286 -415Q2253 -447 2190 -447Q2127 -447 2094 -415Q2062 -383 2062 -321V0ZM2799 0Q2729 0 2690 -36Q2652 -71 2652 -144V-456H2552V-600H2654V-780H2834V-600H2966V-456H2836V-144H2980V0Z";
const LIGHT = "M3073 0V-840H3167V0ZM3329 0V-600H3423V0ZM3827 252Q3706 252 3630 201Q3554 150 3540 60H3640Q3668 170 3827 170Q3926 170 3979 123Q4032 76 4032 -12V-114H4027Q4004 -60 3950 -30Q3896 0 3824 0Q3738 0 3675 -38Q3612 -75 3578 -144Q3544 -212 3544 -306Q3544 -447 3620 -530Q3696 -612 3826 -612Q3898 -612 3949 -586Q4000 -560 4030 -510H4072V-600H4176V-500H4126V-5Q4126 116 4048 184Q3969 252 3827 252ZM3846 -82Q3929 -82 3980 -131Q4032 -180 4032 -260V-352Q4032 -432 3980 -481Q3929 -530 3846 -530Q3749 -530 3694 -471Q3638 -412 3638 -306Q3638 -200 3694 -141Q3749 -82 3846 -82ZM4294 0V-840H4388V-500H4392Q4421 -554 4474 -582Q4528 -611 4599 -611Q4712 -611 4779 -545Q4846 -479 4846 -369V0H4752V-355Q4752 -440 4706 -484Q4659 -529 4570 -529Q4482 -529 4435 -484Q4388 -440 4388 -355V0ZM5126 0Q5084 0 5060 -22Q5037 -43 5037 -86V-528H4922V-600H5038V-780H5130V-600H5294V-528H5131V-74H5310V0Z";

type LogoProps = {
  height?: number;
  className?: string;
};

export function Logo({ height = 32, className }: LogoProps) {
  const glow = `nl-logo-${useId().replace(/:/g, "")}`;
  const [, , w, h] = VIEWBOX.split(" ").map(Number);

  return (
    <svg
      viewBox={VIEWBOX}
      height={height}
      width={(height * w) / h}
      className={className}
      role="img"
      aria-label="nightlight"
      style={{ overflow: "visible" }}
    >
      <defs>
        <radialGradient id={glow}>
          <stop offset="0" stopColor="var(--logo-light, #f5b800)" stopOpacity="0.85" />
          <stop offset="0.45" stopColor="var(--logo-light, #f5b800)" stopOpacity="0.28" />
          <stop offset="1" stopColor="var(--logo-light, #f5b800)" stopOpacity="0" />
        </radialGradient>
      </defs>
      <path d={NIGHT} fill="currentColor" />
      <path d={LIGHT} fill="currentColor" />
      <circle cx="3376" cy="-800" r="440" fill={`url(#${glow})`} />
      <circle cx="3376" cy="-800" r="150" fill="var(--logo-light, #f5b800)" />
    </svg>
  );
}

// App icon: the mascot's head on cream, cropped below the face mask.
const HEAD_CROP = "M-10 -10H200V136H137C137 174 114 198 76 198C42 198 17 184 12 156C11 150 10 146 -10 140Z";

export function LogoIcon({ size = 32, className }: { size?: number; className?: string }) {
  const crop = `nl-icon-${useId().replace(/:/g, "")}`;

  return (
    <svg viewBox="0 0 100 100" width={size} height={size} className={className} role="img" aria-label="Nightlight">
      <defs>
        <clipPath id={crop}>
          <path d={HEAD_CROP} />
        </clipPath>
      </defs>
      <rect width="100" height="100" rx="23" fill="#faf8f3" />
      <g transform="translate(1.16 -44.7) scale(0.66)">
        <path d={BODY} fill="#202020" clipPath={`url(#${crop})`} />
        <path d={FACE} fill="#fbfaf8" />
        {EYES.map((d) => (
          <path key={d} d={d} fill="#0e0e0e" />
        ))}
      </g>
    </svg>
  );
}
