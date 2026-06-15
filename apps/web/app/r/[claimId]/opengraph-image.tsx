/**
 * Per-receipt OG share card (E5-T4, PRD §19 Social/OG layer).
 *
 * Next.js App Router convention: this file auto-wires og:image, og:image:alt,
 * twitter:image, and twitter:image:alt on the parent page — no manual <meta>
 * authoring needed.
 *
 * force-dynamic: card is generated on request, never at build. The DB is never
 * touched at build time. Handles missing/unpublishable claims with a neutral
 * fallback card (no crash).
 *
 * Inline styles only — Tailwind does not run inside ImageResponse.
 * No remote font fetches — system fonts (sans-serif / monospace) keep build offline-safe.
 * All copy neutral (AC-7): analyst, asset, direction, outcome only. No recommendation language.
 */

// TASK: E5-T4

import { ImageResponse } from "next/og";

import { getReceipt } from "@/lib/db";
import {
  BRAND,
  CardShell,
  OG_CONTENT_TYPE,
  OG_SIZE,
  StatusPill,
  Wordmark,
  statusColor,
  statusLabel,
} from "@/lib/og";

export const dynamic = "force-dynamic";
export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

type ImageParams = { params: Promise<{ claimId: string }> };

/** Human-readable alt label for a display status (used in og:image:alt only). */
function altStatusLabel(status: string): string {
  if (status === "open") return "open (not yet resolved)";
  return statusLabel(status);
}

export async function generateImageMetadata({ params }: ImageParams) {
  const { claimId: claimIdStr } = await params;
  const claimId = Number(claimIdStr);

  let receipt = null;
  if (Number.isInteger(claimId) && claimId > 0) {
    try {
      receipt = await getReceipt(claimId);
    } catch {
      receipt = null;
    }
  }

  let alt: string;
  if (!receipt) {
    alt = "Brier receipt";
  } else {
    const directionLabel = receipt.direction
      ? receipt.direction.charAt(0).toUpperCase() + receipt.direction.slice(1)
      : null;
    const targetLabel =
      receipt.targetPrice != null
        ? `$${receipt.targetPrice.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`
        : receipt.magnitudePct != null
          ? `${receipt.magnitudePct > 0 ? "+" : ""}${receipt.magnitudePct.toFixed(1)}%`
          : null;
    const assetLine = [receipt.asset, directionLabel, targetLabel].filter(Boolean).join(" ");
    alt = `Brier receipt: ${receipt.analystDisplayName} — ${assetLine} prediction, outcome ${altStatusLabel(receipt.displayStatus)}`;
  }

  return [{ id: claimIdStr, alt, size: OG_SIZE, contentType: OG_CONTENT_TYPE }];
}

export default async function Image({ params }: ImageParams) {
  const { claimId: claimIdStr } = await params;
  const claimId = Number(claimIdStr);

  let receipt = null;
  if (Number.isInteger(claimId) && claimId > 0) {
    try {
      receipt = await getReceipt(claimId);
    } catch {
      receipt = null;
    }
  }

  // Neutral fallback card for unknown/unpublishable claims
  if (!receipt) {
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
              Receipt not found
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
              This receipt is not available or has not been published.
            </span>
          </div>
          <Footer />
        </CardShell>
      ),
      { width: OG_SIZE.width, height: OG_SIZE.height },
    );
  }

  // Build display fields
  const directionLabel = receipt.direction
    ? receipt.direction.charAt(0).toUpperCase() + receipt.direction.slice(1)
    : null;

  const targetLabel = receipt.targetPrice != null
    ? `$${receipt.targetPrice.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`
    : receipt.magnitudePct != null
    ? `${receipt.magnitudePct > 0 ? "+" : ""}${receipt.magnitudePct.toFixed(1)}%`
    : null;

  const horizonLabel = receipt.horizonDeadline
    ? `by ${receipt.horizonDeadline}`
    : receipt.horizonBasis
    ? receipt.horizonBasis.replace(/_/g, " ")
    : null;

  const status = receipt.displayStatus;
  const sColor = statusColor(status);

  return new ImageResponse(
    (
      <CardShell>
        <Wordmark />

        {/* Analyst name */}
        <span
          style={{
            fontFamily: "monospace",
            fontSize: "13px",
            color: BRAND.ink4,
            letterSpacing: "0.10em",
            textTransform: "uppercase",
            marginBottom: "10px",
          }}
        >
          {receipt.analystDisplayName}
        </span>

        {/* Asset + direction + target */}
        <span
          style={{
            fontFamily: "sans-serif",
            fontWeight: 700,
            fontSize: "48px",
            color: BRAND.ink,
            lineHeight: 1.1,
            marginBottom: "12px",
          }}
        >
          {receipt.asset}
          {directionLabel ? (
            <span style={{ color: BRAND.ink3, fontWeight: 400, fontSize: "36px" }}>
              {" "}
              {directionLabel}
              {targetLabel ? ` · ${targetLabel}` : ""}
            </span>
          ) : null}
        </span>

        {/* Horizon */}
        {horizonLabel ? (
          <span
            style={{
              fontFamily: "monospace",
              fontSize: "16px",
              color: BRAND.ink3,
              marginBottom: "28px",
              letterSpacing: "0.02em",
            }}
          >
            {horizonLabel}
          </span>
        ) : (
          <div style={{ marginBottom: "28px" }} />
        )}

        {/* Status + resolution date row */}
        <div style={{ display: "flex", alignItems: "center", gap: "20px" }}>
          <StatusPill status={status} />
          {receipt.resolutionResolvedAt ? (
            <span
              style={{
                fontFamily: "monospace",
                fontSize: "14px",
                color: BRAND.ink4,
                letterSpacing: "0.04em",
              }}
            >
              Resolved {receipt.resolutionResolvedAt.slice(0, 10)}
            </span>
          ) : null}
          {status === "open" ? (
            <span
              style={{
                fontFamily: "monospace",
                fontSize: "14px",
                color: BRAND.ink4,
                letterSpacing: "0.04em",
              }}
            >
              Awaiting resolution
            </span>
          ) : null}
        </div>

        {/* Rule id if resolved */}
        {receipt.resolutionRuleId ? (
          <span
            style={{
              marginTop: "12px",
              fontFamily: "monospace",
              fontSize: "12px",
              color: BRAND.ink4,
              letterSpacing: "0.06em",
            }}
          >
            Rule: {receipt.resolutionRuleId}
          </span>
        ) : null}

        {/* Hairline + footer */}
        <div style={{ flex: 1 }} />
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderTop: `1px solid ${BRAND.line2}`,
            paddingTop: "16px",
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
          {receipt.resolutionMethodologyVersion ? (
            <span
              style={{
                fontFamily: "monospace",
                fontSize: "12px",
                color: sColor,
                letterSpacing: "0.06em",
              }}
            >
              {receipt.resolutionMethodologyVersion}
            </span>
          ) : null}
        </div>
      </CardShell>
    ),
    { width: OG_SIZE.width, height: OG_SIZE.height },
  );
}

/** Fallback footer strip. */
function Footer() {
  return (
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
  );
}
