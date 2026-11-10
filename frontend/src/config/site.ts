// Single place for personal links and deploy URLs.
const apiUrl = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8040").replace(/\/+$/, "");

export const site = {
  productName: "Paperwork AI",
  tagline: "Stop typing invoices into spreadsheets.",
  author: "Pooya Nikbakht",
  githubUrl: "https://github.com/PooyaNikbakht",
  /** Empty hides the code links. */
  repoUrl: "https://github.com/PooyaNikbakht/paperwork-ai" as string,
  portfolioUrl: "https://pooya.website",
  /** The FastAPI backend. Inlined into the browser bundle at build time. */
  apiUrl,
} as const;
