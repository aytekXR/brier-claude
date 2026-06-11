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
  const file = path.join(process.cwd(), "..", "..", "docs", "METHODOLOGY.md");
  const markdown = await fs.readFile(file, "utf-8");

  return (
    <article className="methodology">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </article>
  );
}
