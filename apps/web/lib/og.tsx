/**
 * Shared layout primitives for OG share cards (E5-T4, PRD §19).
 *
 * Used by both opengraph-image.tsx files; factored here because it is used
 * twice (CLAUDE.md: a helper used once stays inlined).
 *
 * Inline styles only — Tailwind does not run inside ImageResponse.
 * No remote font fetches — system fonts only so the build is offline-safe.
 * All copy is neutral (AC-7 firewall): score, claim, outcome only.
 */


/** Brand hex values (BRANDKIT §1). */
export const BRAND = {
  navy: "#16233A",
  navyLifted: "#22324F",
  paper: "#F4F2EC",
  surface: "#FCFBF8",
  ink: "#16191D",
  ink2: "#2C3036",
  ink3: "#565C64",
  ink4: "#8A8F96",
  line: "rgba(21,25,29,0.10)",
  line2: "rgba(21,25,29,0.20)",
  brierBlue: "#2D54CE",
  // FAS bands
  fasElite: "#0E7C66",
  fasSkilled: "#3E7A78",
  fasFlip: "#A8995F",
  fasAnti: "#B06043",
  // Status
  hit: "#0E7C66",
  miss: "#B23A2E",
  partial: "#BC8A2C",
  open: "#4A6CC7",
  void: "#8A8F96",
} as const;

/** Resolve the FAS band hex for a given score. */
export function fasBandColor(score: number): string {
  if (score >= 75) return BRAND.fasElite;
  if (score >= 60) return BRAND.fasSkilled;
  if (score >= 40) return BRAND.fasFlip;
  return BRAND.fasAnti;
}

/** Resolve the status hex for a display status string. */
export function statusColor(status: string): string {
  switch (status) {
    case "hit":
      return BRAND.hit;
    case "miss":
      return BRAND.miss;
    case "partial":
      return BRAND.partial;
    case "open":
      return BRAND.open;
    case "void":
    case "non_falsifiable":
      return BRAND.void;
    default:
      return BRAND.ink4;
  }
}

/** Human-readable label for a display status. */
export function statusLabel(status: string): string {
  switch (status) {
    case "hit":
      return "HIT";
    case "miss":
      return "MISS";
    case "partial":
      return "PARTIAL";
    case "open":
      return "OPEN";
    case "void":
      return "VOID";
    case "non_falsifiable":
      return "NON-FALSIFIABLE";
    default:
      return status.toUpperCase();
  }
}

/** Card dimensions and content type (shared export convention for Next.js OG). */
export const OG_SIZE = { width: 1200, height: 630 };
export const OG_CONTENT_TYPE = "image/png";

/**
 * Outer card shell: navy masthead stripe on the left, paper background.
 * Children render in the main content area.
 */
export function CardShell({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        width: "1200px",
        height: "630px",
        background: BRAND.paper,
        fontFamily: "sans-serif",
      }}
    >
      {/* Left accent stripe — navy, like the product sidebar */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          width: "12px",
          background: BRAND.navy,
          flexShrink: 0,
        }}
      />
      {/* Main content area */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          flex: 1,
          padding: "56px 64px",
        }}
      >
        {children}
      </div>
    </div>
  );
}

/** Wordmark row: "Brier" in brand navy + a hairline rule below. */
export function Wordmark() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        marginBottom: "40px",
      }}
    >
      <span
        style={{
          fontFamily: "serif",
          fontWeight: 600,
          fontSize: "22px",
          color: BRAND.navy,
          letterSpacing: "-0.01em",
        }}
      >
        Brier
      </span>
      <div
        style={{
          marginTop: "12px",
          height: "1px",
          background: BRAND.line2,
        }}
      />
    </div>
  );
}

/** Mono label pill for status (neutral, muted border per BRANDKIT §1). */
export function StatusPill({ status }: { status: string }) {
  const color = statusColor(status);
  const label = statusLabel(status);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "8px",
        padding: "6px 14px",
        border: `1px solid ${color}`,
        borderRadius: "3px",
        background: BRAND.surface,
      }}
    >
      <div
        style={{
          width: "8px",
          height: "8px",
          borderRadius: "50%",
          background: color,
          flexShrink: 0,
        }}
      />
      <span
        style={{
          fontFamily: "monospace",
          fontWeight: 500,
          fontSize: "14px",
          color,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
        }}
      >
        {label}
      </span>
    </div>
  );
}
