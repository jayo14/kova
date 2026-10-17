import Link from "next/link";
import { notFound } from "next/navigation";
import { getAllDocSlugs, getDocBySlug } from "@/lib/docs";
import { DocsToc } from "@/components/docs/docs-toc";
import { CodeCopyManager } from "@/components/docs/code-copy";
import { MaterialIcon } from "@/components/shared/material-icon";

interface DocPageProps {
  params: Promise<{
    slug: string[];
  }>;
}

export async function generateStaticParams() {
  const slugs = getAllDocSlugs();
  return slugs.map((slug) => ({ slug }));
}

export async function generateMetadata({ params }: DocPageProps) {
  const { slug } = await params;
  const doc = await getDocBySlug(slug);
  if (!doc) return { title: "Documentation | Kova" };

  return {
    title: `${doc.title} | Kova Documentation`,
    description: doc.description || `Read about ${doc.title} in the Kova documentation.`,
  };
}

export default async function DocPage({ params }: DocPageProps) {
  const { slug } = await params;
  const doc = await getDocBySlug(slug);

  if (!doc) {
    notFound();
  }

  return (
    <div className="flex flex-col xl:flex-row items-start gap-10">
      {/* Main Reading Column */}
      <article className="flex-1 min-w-0 max-w-3xl">
        {/* Breadcrumb Navigation */}
        <nav className="flex items-center gap-1.5 text-xs text-muted-foreground mb-4">
          <Link href="/docs/quickstart" className="hover:text-foreground transition-colors">
            Docs
          </Link>
          <MaterialIcon name="chevron_right" size={14} className="opacity-50" />
          <span>{doc.group}</span>
          <MaterialIcon name="chevron_right" size={14} className="opacity-50" />
          <span className="text-foreground font-medium truncate">{doc.title}</span>
        </nav>

        {/* Page Header */}
        <header className="mb-8 border-b border-border/40 pb-6">
          <h1 className="font-heading text-3xl sm:text-4xl font-extrabold tracking-tight text-foreground">
            {doc.title}
          </h1>
          {doc.description && (
            <p className="mt-3 text-base text-muted-foreground leading-relaxed">
              {doc.description}
            </p>
          )}
        </header>

        {/* Markdown Rendered Content */}
        <div
          className="doc-content prose prose-zinc dark:prose-invert max-w-none text-foreground/90 leading-relaxed text-sm sm:text-[15px] space-y-4"
          dangerouslySetInnerHTML={{ __html: doc.contentHtml }}
        />

        {/* Code copy manager script activator */}
        <CodeCopyManager />

        {/* Previous & Next Footer Navigation Cards */}
        <nav className="mt-12 pt-6 border-t border-border/40 grid grid-cols-1 sm:grid-cols-2 gap-4">
          {doc.prev ? (
            <Link
              href={`/docs/${doc.prev.slug}`}
              className="group flex flex-col p-4 rounded-xl border border-border/80 bg-secondary/20 hover:bg-secondary/50 hover:border-border transition-all"
            >
              <div className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground group-hover:text-foreground">
                <MaterialIcon name="arrow_back" size={12} />
                <span>Previous</span>
              </div>
              <span className="mt-1 font-semibold text-sm text-foreground group-hover:text-primary transition-colors">
                {doc.prev.title}
              </span>
            </Link>
          ) : (
            <div />
          )}

          {doc.next ? (
            <Link
              href={`/docs/${doc.next.slug}`}
              className="group flex flex-col items-end p-4 rounded-xl border border-border/80 bg-secondary/20 hover:bg-secondary/50 hover:border-border transition-all text-right"
            >
              <div className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground group-hover:text-foreground">
                <span>Next</span>
                <MaterialIcon name="arrow_forward" size={12} />
              </div>
              <span className="mt-1 font-semibold text-sm text-foreground group-hover:text-primary transition-colors">
                {doc.next.title}
              </span>
            </Link>
          ) : null}
        </nav>
      </article>

      {/* Desktop Sticky Table of Contents on the Right */}
      <aside className="hidden xl:block w-60 shrink-0 sticky top-24 pt-2">
        <DocsToc headings={doc.headings} />
      </aside>
    </div>
  );
}
