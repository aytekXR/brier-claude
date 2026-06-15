/**
 * Per-analyst OG share card (E5-T4, PRD §19 Social/OG layer).
 *
 * Next.js App Router convention: this file auto-wires og:image, og:image:alt,
 * twitter:image, and twitter:image:alt on the parent page — no manual <meta>
 * authoring needed.
 *
 * force-dynamic: card is generated on request, never at build. The DB is never
 * touched at build time. Handles unknown slugs with a neutral fallback card (no crash).
 *
 * Inline styles only — Tailwind does not run inside ImageResponse.
 * No remote font fetches — system fonts (sans-serif / monospace) keep build offline-safe.
 * All copy neutral (AC-7): analyst name, FAS score, n, falsifiability, ranked/provisional.
 * No recommendation language anywhere (AC-7 firewall).
 */

// TASK: E5-T4

import { ImageResponse } from "next/og";

import { getAnalyst } from "@/lib/db";
import {
  BRAND,
  CardShell,
  OG_CONTENT_TYPE,
  OG_SIZE,
  Wordmark,
  fasBandColor,
} from "@/lib/og";

export const dynamic = "force-dynamic";
export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

type ImageParams = { params: Promise<{ slug: string }> };

export async function generateImageMetadata({ params }: ImageParams) {
  const { slug } = await params;

  let analyst = null;
  try {
    analyst = await getAnalyst(slug);
  } catch {
    analyst = null;
  }

  let alt: string;
  if (!analyst) {
    alt = "Brier analyst scorecard";
  } else {
    const rankedLabel = analyst.ranked ? "ranked" : "provisional";
    alt = `Brier analyst scorecard: ${analyst.displayName} — FAS ${analyst.fas.toFixed(1)}, ${analyst.nResolved} resolved claims, falsifiability ${analyst.falsifiability.toFixed(2)}, ${rankedLabel}`;
  }

  return [{ id: slug, alt, size: OG_SIZE, contentType: OG_CONTENT_TYPE }];
}

export default async function Image({ params }: ImageParams) {
  const { slug } = await params;

  let analyst = null;
  try {
    analyst = await getAnalyst(slug);
  } catch {
    analyst = null;
  }

  // Neutral fallback card for unknown slug
  if (!analyst) {
    return new ImageResponse(
      (
        <CardShell>
          <Wordmark />
          <div style={{ display: "flex", flexDirection: "column", flex: 1, justifyContent: "center" }}>
            <span
              style={{
                fontFamily: "monospace",
                fontSize: "13px",
                color: BRAND.ink4,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                marginBottom: "16px",
              }}
            >
              Analyst not found
            </span>
            <span
              style={{
                fontFamily: "sans-serif",
                fontSize: "32px",
                fontWeight: 600,
                color: BRAND.ink,
                lineHeight: 1.2,
              }}
            >
              Brier tracks prediction accuracy
            </span>
            <span
              style={{
                marginTop: "16px",
                fontFamily: "sans-serif",
                fontSize: "18px",
                color: BRAND.ink3,
              }}
            >
              This analyst is not in the registry.
            </span>
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              borderTop: `1px solid ${BRAND.line2}`,
              paddingTop: "16px",
              marginTop: "auto",
            }}
          >
            <span
              style={{
                fontFamily: "monospace",
                fontSize: "12px",
                color: BRAND.ink4,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              Brier · prediction track record
            </span>
          </div>
        </CardShell>
      ),
      { width: OG_SIZE.width, height: OG_SIZE.height },
    );
  }

  const bandColor = fasBandColor(analyst.fas);
  const rankedLabel = analyst.ranked ? "Ranked" : analyst.provisional ? "Provisional" : "Unranked";

  // Outcome totals for compact display
  const { hit, miss, partial, open, void: voidCount } = analyst.outcomeCounts;

  return new ImageResponse(
    (
      <CardShell>
        <Wordmark />

        {/* Main content: FAS badge + analyst info side by side */}
        <div style={{ display: "flex", alignItems: "flex-start", gap: "48px", flex: 1 }}>
          {/* Left: large FAS badge block */}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "8px" }}>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                width: "140px",
                height: "140px",
                borderRadius: "6px",
                background: bandColor,
              }}
            >
              <span
                style={{
                  fontFamily: "monospace",
                  fontWeight: 700,
                  fontSize: "52px",
                  color: "#FFFFFF",
                  lineHeight: 1,
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {analyst.fas.toFixed(1)}
              </span>
              <span
                style={{
                  fontFamily: "monospace",
                  fontSize: "10px",
                  color: "rgba(255,255,255,0.80)",
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  marginTop: "6px",
                }}
              >
                {fasLabel(analyst.fas)}
              </span>
            </div>
            {/* Ranked / Provisional tag */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                padding: "4px 10px",
                border: `1px solid ${BRAND.line2}`,
                borderRadius: "3px",
                background: BRAND.surface,
              }}
            >
              <span
                style={{
                  fontFamily: "monospace",
                  fontSize: "10px",
                  color: BRAND.ink4,
                  letterSpacing: "0.10em",
                  textTransform: "uppercase",
                }}
              >
                {rankedLabel}
              </span>
            </div>
          </div>

          {/* Right: analyst name + components */}
          <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
            {/* Analyst name */}
            <span
              style={{
                fontFamily: "sans-serif",
                fontWeight: 700,
                fontSize: "42px",
                color: BRAND.ink,
                lineHeight: 1.1,
                marginBottom: "24px",
              }}
            >
              {analyst.displayName}
            </span>

            {/* Component scores — mono, ledger-exact */}
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <ComponentRow label="Methodology" value={analyst.methodologyVersion} plain />
              <ComponentRow
                label="n resolved"
                value={String(analyst.nResolved)}
              />
              <ComponentRow
                label="Falsifiability"
                value={analyst.falsifiability.toFixed(2)}
              />
              <ComponentRow
                label="Outcomes"
                value={`${hit}H · ${miss}M${partial > 0 ? ` · ${partial}P` : ""} · ${open} open${voidCount > 0 ? ` · ${voidCount}V` : ""}`}
                plain
              />
            </div>
          </div>
        </div>

        {/* Footer */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderTop: `1px solid ${BRAND.line2}`,
            paddingTop: "16px",
            marginTop: "32px",
          }}
        >
          <span
            style={{
              fontFamily: "monospace",
              fontSize: "12px",
              color: BRAND.ink4,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
            }}
          >
            Brier · prediction track record
          </span>
          <span
            style={{
              fontFamily: "monospace",
              fontSize: "12px",
              color: BRAND.ink4,
              letterSpacing: "0.06em",
            }}
          >
            We publish statistics about public statements.
          </span>
        </div>
      </CardShell>
    ),
    { width: OG_SIZE.width, height: OG_SIZE.height },
  );
}

/** Band label text for a FAS score. */
function fasLabel(score: number): string {
  if (score >= 75) return "Elite";
  if (score >= 60) return "Skilled";
  if (score >= 40) return "Coin-flip";
  return "Anti-skilled";
}

/** Single mono key-value row for the component display. */
function ComponentRow({
  label,
  value,
  plain = false,
}: {
  label: string;
  value: string;
  plain?: boolean;
}) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: "12px" }}>
      <span
        style={{
          fontFamily: "monospace",
          fontSize: "11px",
          color: BRAND.ink4,
          letterSpacing: "0.10em",
          textTransform: "uppercase",
          minWidth: "130px",
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontFamily: "monospace",
          fontWeight: plain ? 400 : 500,
          fontSize: "17px",
          color: plain ? BRAND.ink3 : BRAND.ink2,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </span>
    </div>
  );
}
