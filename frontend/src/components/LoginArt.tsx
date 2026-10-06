/** Light, locally bundled sign-in wallpapers (no external images). Each preset is a scalable SVG that fills the
 *  left side of the sign-in page; colours follow the active theme through CSS variables where it suits the art. */

export const LOGIN_PRESETS: [string, string][] = [
  ["minimal", "Minimal"], ["nature", "Nature"], ["travel", "Travel"], ["family", "Family"], ["neutral", "Neutral"],
];

function Minimal() {
  return (
    <>
      <rect width="800" height="1000" fill="var(--brand-softer, #eef5ef)" />
      <circle cx="680" cy="140" r="220" fill="var(--brand-soft, #dcebe0)" opacity=".8" />
      <circle cx="80" cy="900" r="260" fill="var(--brand-soft, #dcebe0)" opacity=".6" />
      <g transform="translate(150 560)" opacity=".95">
        {[0, 1, 2].map((i) => (
          <g key={i} transform={`translate(${i * 175} ${i % 2 ? 30 : 0})`}>
            <path d="M0 22a14 14 0 0 1 14-14h46l16 16h60a14 14 0 0 1 14 14v92a14 14 0 0 1-14 14H14A14 14 0 0 1 0 130z" fill="#fff" stroke="var(--brand, #1f5135)" strokeOpacity=".25" strokeWidth="3" />
            <rect x="22" y="58" width="90" height="10" rx="5" fill="var(--brand, #1f5135)" opacity=".25" />
            <rect x="22" y="80" width="60" height="10" rx="5" fill="var(--brand, #1f5135)" opacity=".15" />
          </g>
        ))}
      </g>
    </>
  );
}

function Nature() {
  return (
    <>
      <defs>
        <linearGradient id="la-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#e9f4fb" /><stop offset="1" stopColor="#f7fbf3" /></linearGradient>
      </defs>
      <rect width="800" height="1000" fill="url(#la-sky)" />
      <circle cx="610" cy="250" r="70" fill="#ffe7a8" />
      <path d="M0 640 Q160 540 330 610 T800 560 V1000 H0z" fill="#cfe6cf" />
      <path d="M0 740 Q220 650 430 720 T800 690 V1000 H0z" fill="#b5d9b8" />
      <path d="M0 850 Q260 780 520 840 T800 820 V1000 H0z" fill="#9ccca3" />
      {[[120, 700, 1], [210, 690, 0.8], [600, 660, 1.1], [690, 680, 0.85]].map(([x, y, s], i) => (
        <g key={i} transform={`translate(${x} ${y}) scale(${s})`}>
          <rect x="-6" y="0" width="12" height="46" fill="#8a6b4f" opacity=".7" />
          <path d="M0 -90 L48 10 H-48z" fill="#6fae7a" />
          <path d="M0 -130 L38 -40 H-38z" fill="#7fbb88" />
        </g>
      ))}
      <path d="M140 300 q20 -14 40 0 q20 -14 40 0" fill="none" stroke="#7e95a8" strokeWidth="4" strokeLinecap="round" />
      <path d="M250 360 q14 -10 28 0 q14 -10 28 0" fill="none" stroke="#7e95a8" strokeWidth="3" strokeLinecap="round" />
    </>
  );
}

function Travel() {
  return (
    <>
      <defs>
        <linearGradient id="la-tsky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#e6f0fb" /><stop offset="1" stopColor="#fbf6ee" /></linearGradient>
      </defs>
      <rect width="800" height="1000" fill="url(#la-tsky)" />
      {[[140, 260, 1], [560, 380, 1.3], [300, 520, 0.9]].map(([x, y, s], i) => (
        <g key={i} transform={`translate(${x} ${y}) scale(${s})`} fill="#fff">
          <ellipse cx="0" cy="0" rx="70" ry="26" /><ellipse cx="-30" cy="-16" rx="34" ry="26" /><ellipse cx="22" cy="-22" rx="40" ry="30" />
        </g>
      ))}
      <path d="M90 820 C 260 640, 420 760, 560 520 S 700 300, 720 260" fill="none" stroke="#7a8fb0" strokeWidth="4" strokeDasharray="4 14" strokeLinecap="round" />
      <g transform="translate(720 250) rotate(-35)">
        <path d="M-40 0 L40 -6 Q56 0 40 6z" fill="#2a66b0" opacity=".85" />
        <path d="M-6 -4 L-30 -40 L-16 -40 L14 -4z M-6 4 L-30 40 L-16 40 L14 4z" fill="#2a66b0" opacity=".7" />
      </g>
      {[[90, 820], [560, 520]].map(([x, y], i) => (
        <g key={i} transform={`translate(${x} ${y})`}>
          <path d="M0 0 C-22 -26 -22 -56 0 -56 C22 -56 22 -26 0 0z" fill="#e07b00" opacity=".85" /><circle cx="0" cy="-36" r="8" fill="#fff" />
        </g>
      ))}
      <g transform="translate(470 760) rotate(-8)">
        <rect width="150" height="200" rx="12" fill="#3f6f5a" opacity=".9" />
        <circle cx="75" cy="80" r="34" fill="none" stroke="#e9d8a6" strokeWidth="4" />
        <path d="M41 80h68M75 46c-16 20-16 48 0 68M75 46c16 20 16 48 0 68" fill="none" stroke="#e9d8a6" strokeWidth="3" />
        <rect x="35" y="140" width="80" height="8" rx="4" fill="#e9d8a6" />
      </g>
    </>
  );
}

function Family() {
  const people: [number, number, number, string][] = [[250, 700, 1.15, "#e7a977"], [390, 690, 1.25, "#7aa6c9"], [520, 735, 0.85, "#9ccc7c"], [610, 745, 0.75, "#d58fb5"]];
  return (
    <>
      <rect width="800" height="1000" fill="#fbf5ee" />
      <circle cx="420" cy="430" r="300" fill="#f6e6d4" />
      <g transform="translate(300 300)">
        <path d="M0 140 L120 40 L240 140 V300 H0z" fill="#fff" stroke="#d9b48f" strokeWidth="4" />
        <path d="M-20 150 L120 30 L260 150" fill="none" stroke="#c98a5a" strokeWidth="10" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="95" y="200" width="50" height="100" rx="6" fill="#f0d2b4" />
        <rect x="30" y="170" width="40" height="40" rx="4" fill="#e9f1f7" /><rect x="170" y="170" width="40" height="40" rx="4" fill="#e9f1f7" />
      </g>
      {people.map(([x, y, s, c], i) => (
        <g key={i} transform={`translate(${x} ${y}) scale(${s})`}>
          <circle cx="0" cy="-70" r="26" fill={c} opacity=".9" />
          <path d="M-38 40 Q-38 -36 0 -36 Q38 -36 38 40z" fill={c} opacity=".75" />
        </g>
      ))}
      <path d="M400 560 c-12 -18 -40 -10 -40 10 c0 18 40 40 40 40 s40 -22 40 -40 c0 -20 -28 -28 -40 -10z" fill="#e0708a" opacity=".8" />
      <rect x="0" y="790" width="800" height="210" fill="#f3e4d2" />
    </>
  );
}

function Neutral() {
  return (
    <>
      <rect width="800" height="1000" fill="#f5f5f2" />
      {Array.from({ length: 14 }).map((_, i) => <path key={i} d={`M0 ${120 + i * 64} Q400 ${90 + i * 64} 800 ${130 + i * 64}`} fill="none" stroke="#e3e3dd" strokeWidth="2" />)}
      <rect x="470" y="160" width="220" height="290" rx="14" fill="#fff" stroke="#e1e1da" strokeWidth="3" />
      <rect x="500" y="200" width="140" height="12" rx="6" fill="#e6e6df" /><rect x="500" y="228" width="100" height="12" rx="6" fill="#ecece6" />
      <rect x="430" y="210" width="220" height="290" rx="14" fill="#fff" stroke="#e1e1da" strokeWidth="3" />
      <rect x="460" y="250" width="150" height="12" rx="6" fill="#e1e1da" /><rect x="460" y="278" width="110" height="12" rx="6" fill="#ebebe5" />
    </>
  );
}

const ART: Record<string, () => JSX.Element> = { minimal: Minimal, nature: Nature, travel: Travel, family: Family, neutral: Neutral };

export default function LoginArt({ design }: { design: string }) {
  const Art = ART[design] || Minimal;
  return (
    <svg className="auth-wallpaper" viewBox="0 0 800 1000" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
      <Art />
    </svg>
  );
}
