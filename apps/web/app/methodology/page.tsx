import { promises as fs } from "node:fs";
import path from "node:path";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export const dynamic = "force-dynamic";

/**
 * FR-404: the public methodology page. Renders docs/METHODOLOGY.md verbatim —
 * the published document IS the spec the scoring engine implements, so the
 * page can never drift from the formulas.
 */
export default async function MethodologyPage() {
  let markdown: string;
  try {
    const file = path.join(process.cwd(), "..", "..", "docs", "METHODOLOGY.md");
    markdown = await fs.readFile(file, "utf-8");
  } catch {
    // Missing file or unexpected working directory: degrade gracefully rather
    // than 500, matching the fallback discipline of the DB-reading routes.
    return (
      <article className="methodology">
        <p>The methodology document is temporarily unavailable. Please check back shortly.</p>
      </article>
    );
  }

  return (
    <article className="methodology">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </article>
  );
}
