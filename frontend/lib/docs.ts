import fs from "fs";
import path from "path";
import { marked } from "marked";

export interface DocHeading {
  id: string;
  text: string;
  level: number;
}

export interface DocPage {
  slug: string;
  title: string;
  description?: string;
  group: string;
  contentHtml: string;
  headings: DocHeading[];
  prev?: { slug: string; title: string };
  next?: { slug: string; title: string };
}

export interface DocNavigationItem {
  title: string;
  slug: string;
  href: string;
  description?: string;
}

export interface DocNavigationGroup {
  group: string;
  pages: DocNavigationItem[];
}

export interface DocsConfig {
  name: string;
  navigation: DocNavigationGroup[];
}

const DOCS_DIRECTORY = path.join(process.cwd(), "content/docs");

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/<[^>]+>/g, "")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

function parseFrontmatter(rawContent: string): {
  data: { title?: string; description?: string };
  content: string;
} {
  const match = rawContent.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/);
  if (!match) {
    return { data: {}, content: rawContent };
  }

  const yamlBlock = match[1];
  const markdownContent = match[2];
  const data: { title?: string; description?: string } = {};

  for (const line of yamlBlock.split(/\r?\n/)) {
    const colonIdx = line.indexOf(":");
    if (colonIdx > -1) {
      const key = line.slice(0, colonIdx).trim();
      let val = line.slice(colonIdx + 1).trim();
      if (
        (val.startsWith('"') && val.endsWith('"')) ||
        (val.startsWith("'") && val.endsWith("'"))
      ) {
        val = val.slice(1, -1);
      }
      if (key === "title") data.title = val;
      if (key === "description") data.description = val;
    }
  }

  return { data, content: markdownContent };
}

export function getDocsConfig(): DocsConfig {
  const configPath = path.join(DOCS_DIRECTORY, "mint.json");
  if (!fs.existsSync(configPath)) {
    return { name: "Kova Documentation", navigation: [] };
  }

  try {
    const raw = fs.readFileSync(configPath, "utf-8");
    const parsed = JSON.parse(raw);

    const navigation: DocNavigationGroup[] = (parsed.navigation || []).map(
      (grp: { group: string; pages: string[] }) => {
        const pages: DocNavigationItem[] = grp.pages.map((pSlug) => {
          const filePath = path.join(DOCS_DIRECTORY, `${pSlug}.mdx`);
          let title = pSlug.split("/").pop()?.replace(/-/g, " ") || pSlug;
          let description: string | undefined = undefined;

          if (fs.existsSync(filePath)) {
            const fileRaw = fs.readFileSync(filePath, "utf-8");
            const { data } = parseFrontmatter(fileRaw);
            if (data.title) title = data.title;
            if (data.description) description = data.description;
          }

          return {
            title,
            slug: pSlug,
            href: `/docs/${pSlug}`,
            description,
          };
        });

        return {
          group: grp.group,
          pages,
        };
      }
    );

    return {
      name: parsed.name || "Kova Documentation",
      navigation,
    };
  } catch (err) {
    console.error("Failed to parse mint.json:", err);
    return { name: "Kova Documentation", navigation: [] };
  }
}

export function getAllDocSlugs(): string[][] {
  const config = getDocsConfig();
  const slugs: string[][] = [];

  for (const group of config.navigation) {
    for (const page of group.pages) {
      slugs.push(page.slug.split("/"));
    }
  }

  return slugs;
}

export function getAllDocsFlatList(): DocNavigationItem[] {
  const config = getDocsConfig();
  const list: DocNavigationItem[] = [];
  for (const group of config.navigation) {
    for (const page of group.pages) {
      list.push(page);
    }
  }
  return list;
}

function preprocessCallouts(md: string): string {
  return md.replace(
    /^> \[!(NOTE|TIP|WARNING|IMPORTANT|CAUTION)\][^\n]*\n((?:> ?[^\n]*(?:\n|$))*)/gm,
    (_, type: string, body: string) => {
      const lines = body
        .split("\n")
        .map((l) => l.replace(/^> ?/, ""))
        .join("\n")
        .trim();
      const inner = marked.parse(lines, { async: false }) as string;
      const label =
        type === "CAUTION" ? "Warning" : type.charAt(0) + type.slice(1).toLowerCase();
      return `<div class="doc-callout doc-callout-${type.toLowerCase()}" role="note"><p class="doc-callout-label"><span class="material-symbols-rounded doc-callout-icon" aria-hidden="true">${type === "TIP" ? "lightbulb" : type === "NOTE" ? "info" : type === "WARNING" || type === "CAUTION" ? "warning" : "priority_high"}</span>${label}</p><div class="doc-callout-body">${inner}</div></div>\n\n`;
    }
  );
}

function preprocessTabs(md: string): string {
  return md.replace(
    /:::tabs\n([\s\S]*?)\n:::\/tabs/g,
    (_, body: string) => {
      const tabRegex = /:::tab\[([^\]]+)\]\n([\s\S]*?)\n:::\/tab/g;
      const tabs: { label: string; content: string }[] = [];
      let m: RegExpExecArray | null;
      while ((m = tabRegex.exec(body)) !== null) {
        tabs.push({ label: m[1].trim(), content: m[2].trim() });
      }
      if (tabs.length === 0) return "";

      const tabIdBase = `tab-${Math.random().toString(36).slice(2, 9)}`;
      const list = tabs
        .map(
          (t, i) =>
            `<button type="button" role="tab" aria-selected="${i === 0}" data-tab-target="${tabIdBase}-${i}" class="doc-tab${i === 0 ? " doc-tab-active" : ""}">${t.label}</button>`
        )
        .join("");
      const panels = tabs
        .map(
          (t, i) =>
            `<div role="tabpanel" data-tab-panel="${tabIdBase}-${i}" class="doc-tab-panel${i === 0 ? " doc-tab-panel-active" : ""}">${marked.parse(t.content, { async: false })}</div>`
        )
        .join("\n");

      return `<div class="doc-tabs" data-doc-tabs><div role="tablist" class="doc-tabs-list">${list}</div>${panels}</div>\n\n`;
    }
  );
}

let activeHeadings: DocHeading[] = [];

marked.use({
  renderer: {
    heading({ text, depth }: { text: string; depth: number }) {
      const cleanText = text.replace(/<[^>]+>/g, "");
      const id = slugify(cleanText);

      if (depth === 2 || depth === 3) {
        activeHeadings.push({ id, text: cleanText, level: depth });
      }

      return `<h${depth} id="${id}" class="doc-heading group scroll-mt-24 font-heading font-semibold text-foreground tracking-tight ${
        depth === 1
          ? "text-3xl sm:text-4xl mt-2 mb-6"
          : depth === 2
          ? "text-2xl mt-12 mb-4 border-b border-border/40 pb-2"
          : "text-xl mt-8 mb-3"
      }">
          <a href="#${id}" class="hover:underline flex items-center gap-2">
            ${text}
          </a>
        </h${depth}>\n`;
    },
  } as any,
});

export async function getDocBySlug(slugArray: string[]): Promise<DocPage | null> {
  const slug = slugArray.join("/");
  const filePath = path.join(DOCS_DIRECTORY, `${slug}.mdx`);

  if (!fs.existsSync(filePath)) {
    return null;
  }

  const fileRaw = fs.readFileSync(filePath, "utf-8");
  const { data, content } = parseFrontmatter(fileRaw);

  activeHeadings = [];
  const contentHtml = await marked.parse(
    preprocessTabs(preprocessCallouts(content))
  );
  const headings = activeHeadings;
  activeHeadings = [];

  // Compute prev/next
  const flatList = getAllDocsFlatList();
  const currentIndex = flatList.findIndex((item) => item.slug === slug);
  const prev = currentIndex > 0 ? { slug: flatList[currentIndex - 1].slug, title: flatList[currentIndex - 1].title } : undefined;
  const next =
    currentIndex > -1 && currentIndex < flatList.length - 1
      ? { slug: flatList[currentIndex + 1].slug, title: flatList[currentIndex + 1].title }
      : undefined;

  // Determine group name
  const config = getDocsConfig();
  let groupName = "Documentation";
  for (const g of config.navigation) {
    if (g.pages.some((p) => p.slug === slug)) {
      groupName = g.group;
      break;
    }
  }

  return {
    slug,
    title: data.title || slug.split("/").pop() || "Documentation",
    description: data.description,
    group: groupName,
    contentHtml,
    headings,
    prev,
    next,
  };
}
