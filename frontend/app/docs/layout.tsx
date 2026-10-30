import Script from "next/script";
import { getDocsConfig } from "@/lib/docs";
import { DocsShell } from "@/components/docs/docs-shell";

export const metadata = {
  title: {
    template: "%s | Kova Documentation",
    default: "Documentation | Kova",
  },
  description: "Official guides, concepts, and API reference for the Kova Autonomous Verification Platform.",
};

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  const config = getDocsConfig();

  return (
    <>
      <DocsShell navigation={config.navigation}>{children}</DocsShell>
      <Script
        src="https://buttons.github.io/buttons.js"
        strategy="afterInteractive"
      />
    </>
  );
}
