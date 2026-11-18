import type { SVGProps } from "react";

type Shape = string | { rect: [number, number, number, number, number] } | { circle: [number, number, number] };

const ICONS = {
  home: ["M3 11.5 12 4l9 7.5", "M5.5 10v9.5h13V10", "M10 19.5v-5h4v5"],
  phone: ["M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a1 1 0 0 1-1 1A16 16 0 0 1 4 5a1 1 0 0 1 1-1z"],
  "phone-end": ["M3 13.5c5-4.5 13-4.5 18 0l-2 3.2-3.8-1.3v-2.8a9.5 9.5 0 0 0-6.4 0v2.8L5 16.7z"],
  history: ["M12 7v5l3 2", "M3.5 12a8.5 8.5 0 1 0 2.6-6.1", "M3.5 4.5v4h4"],
  sliders: ["M4 7h9", "M17 7h3", { circle: [15, 7, 2] }, "M4 17h3", "M11 17h9", { circle: [9, 17, 2] }],
  shield: ["M12 3 19.5 6v5.8c0 4.4-3 7.4-7.5 9.2-4.5-1.8-7.5-4.8-7.5-9.2V6z"],
  "shield-check": ["M12 3 19.5 6v5.8c0 4.4-3 7.4-7.5 9.2-4.5-1.8-7.5-4.8-7.5-9.2V6z", "M9 12l2.2 2.2L15.5 10"],
  flask: ["M9.5 3h5", "M10.5 3v6L5 18.5A1.6 1.6 0 0 0 6.4 21h11.2a1.6 1.6 0 0 0 1.4-2.5L13.5 9V3", "M8 15h8"],
  mic: [{ rect: [9, 3, 6, 11, 3] }, "M5.5 11.5a6.5 6.5 0 0 0 13 0", "M12 18v3"],
  "mic-off": [{ rect: [9, 3, 6, 11, 3] }, "M5.5 11.5a6.5 6.5 0 0 0 13 0", "M12 18v3", "M4 4l16 16"],
  play: ["M7 5v14l11-7z"],
  stop: [{ rect: [6, 6, 12, 12, 2] }],
  check: ["M5 12.5l4.5 4.5L19 7.5"],
  x: ["M6 6l12 12", "M18 6 6 18"],
  "chevron-down": ["M6 9l6 6 6-6"],
  "chevron-up": ["M6 15l6-6 6 6"],
  "chevron-right": ["M9 6l6 6-6 6"],
  "chevron-left": ["M15 6l-6 6 6 6"],
  search: [{ circle: [11, 11, 6.5] }, "M16 16l4.5 4.5"],
  trash: ["M4 7h16", "M9.5 7V4.5h5V7", "M6.5 7l1 13h9l1-13", "M10 11v5.5", "M14 11v5.5"],
  download: ["M12 4v11", "M7.5 11 12 15.5 16.5 11", "M5 19.5h14"],
  upload: ["M12 15.5V4.5", "M7.5 9 12 4.5 16.5 9", "M5 19.5h14"],
  globe: [{ circle: [12, 12, 9] }, "M3 12h18", "M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"],
  language: ["M4 6h9", "M8.5 4v2", "M6 6c.5 3 2.5 5.5 5.5 7", "M11.5 6c-.5 3-3 6-6.5 7.5", "M13 20l4-9 4 9", "M14.4 17h5.2"],
  lock: [{ rect: [5, 11, 14, 9.5, 2.5] }, "M8 11V8a4 4 0 0 1 8 0v3"],
  alert: ["M12 4 21 19.5H3z", "M12 10v4.5", "M12 17v.01"],
  info: [{ circle: [12, 12, 9] }, "M12 11v5.5", "M12 7.6v.01"],
  copy: [{ rect: [9, 9, 11, 11, 2] }, "M15 9V6.5A2.5 2.5 0 0 0 12.5 4h-6A2.5 2.5 0 0 0 4 6.5v6A2.5 2.5 0 0 0 6.5 15H9"],
  user: [{ circle: [12, 8.5, 3.5] }, "M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5"],
  "user-check": [{ circle: [10, 8.5, 3.5] }, "M3.5 20c.7-3.4 3.2-5.2 6.5-5.2", "M15 16l2.2 2.2 4-4.2"],
  sun: [
    { circle: [12, 12, 4] },
    "M12 2.5v2.2",
    "M12 19.3v2.2",
    "M2.5 12h2.2",
    "M19.3 12h2.2",
    "M5.3 5.3l1.6 1.6",
    "M17.1 17.1l1.6 1.6",
    "M18.7 5.3l-1.6 1.6",
    "M6.9 17.1l-1.6 1.6",
  ],
  moon: ["M20 14.5A8.5 8.5 0 1 1 9.5 4 6.8 6.8 0 0 0 20 14.5z"],
  monitor: [{ rect: [3, 4.5, 18, 12, 2] }, "M9 20.5h6", "M12 16.5v4"],
  bell: ["M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 2H5z", "M10 20.5a2.2 2.2 0 0 0 4 0"],
  "arrow-right": ["M4.5 12h15", "M13.5 6l6 6-6 6"],
  "arrow-left": ["M19.5 12h-15", "M10.5 6l-6 6 6 6"],
  plus: ["M12 5v14", "M5 12h14"],
  refresh: ["M20 12a8 8 0 1 1-2.5-5.8", "M20 4.5v4.8h-4.8"],
  external: ["M14 4h6v6", "M20 4l-9 9", "M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"],
  filter: ["M4 5.5h16l-6 7.5v5.5l-4 1.5V13z"],
  send: ["M20.5 3.5 10 14", "M20.5 3.5l-6.5 17-3.5-6.5-6.5-3.5z"],
  wave: ["M5 10v4", "M9 7v10", "M13 4v16", "M17 7v10", "M21 10v4"],
  key: [{ circle: [8, 15, 3.5] }, "M10.5 12.5 19 4", "M16 7l2.5 2.5", "M14 9l2 2"],
  file: ["M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z", "M14 3v5h5"],
  bolt: ["M13 3 5 13.5h6L10 21l9-11h-6z"],
  ban: [{ circle: [12, 12, 9] }, "M5.6 5.6l12.8 12.8"],
  handoff: ["M7 8h12l-3.5-3.5", "M17 16H5l3.5 3.5"],
  clock: [{ circle: [12, 12, 9] }, "M12 7v5l3 2"],
  cpu: [{ rect: [6, 6, 12, 12, 2] }, "M9 2.5V6", "M15 2.5V6", "M9 18v3.5", "M15 18v3.5", "M2.5 9H6", "M2.5 15H6", "M18 9h3.5", "M18 15h3.5"],
  list: ["M8 6h12", "M8 12h12", "M8 18h12", "M4 6h.01", "M4 12h.01", "M4 18h.01"],
  eye: ["M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z", { circle: [12, 12, 3] }],
} satisfies Record<string, Shape[]>;

export type IconName = keyof typeof ICONS;

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  size?: number;
  /** When set the icon is exposed to assistive tech; otherwise it is decorative. */
  title?: string;
}

export function Icon({ name, size = 20, title, className, ...rest }: IconProps) {
  const shapes: Shape[] = ICONS[name];
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      focusable="false"
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      {shapes.map((shape, index) => {
        if (typeof shape === "string") return <path key={index} d={shape} />;
        if ("rect" in shape) {
          const [x, y, width, height, rx] = shape.rect;
          return <rect key={index} x={x} y={y} width={width} height={height} rx={rx} />;
        }
        const [cx, cy, r] = shape.circle;
        return <circle key={index} cx={cx} cy={cy} r={r} />;
      })}
    </svg>
  );
}
