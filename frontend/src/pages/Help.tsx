import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api } from "../api";
import { HelpTip, Icon, renderMarkdown, Skeleton, useAsync } from "../components/ui";

type Guide = { slug: string; title: string; category: string; audience: string; reviewed?: string | null; excerpt?: string };

/** Help & documentation: categories, search, breadcrumbs, table of contents, callouts and screenshots next to the
 * steps. The same Markdown files are the repository documentation (docs/guides). */
export default function HelpPage() {
  const { slug } = useParams();
  const loc = useLocation();
  const [q, setQ] = useState("");
  const [navOpen, setNavOpen] = useState(false); // phone/tablet: the list is rendered only while "Browse guides" is open
  const [query, setQuery] = useState("");
  useEffect(() => { const t = setTimeout(() => setQuery(q), 250); return () => clearTimeout(t); }, [q]);
  const index = useAsync(() => api<{ guides: Guide[]; categories: string[]; version: string }>("help", { query: { q: query } }), [query]);
  const all = useAsync(() => api<{ guides: Guide[]; categories: string[]; version: string }>("help"), []);
  const [guide, setGuide] = useState<(Guide & { markdown: string }) | null>(null);
  useEffect(() => {
    setGuide(null);
    if (slug) api(`help/${slug}`).then(setGuide).catch(() => setGuide({ slug: slug || "", title: "Not found", category: "", audience: "all", markdown: "# Not found\nThis guide does not exist, or it is not available to your account." }));
  }, [slug]);
  const html = useMemo(() => (guide ? renderMarkdown(guide.markdown) : ""), [guide]);
  const toc = useMemo(() => {
    if (!guide) return [] as { id: string; text: string; level: number }[];
    const div = document.createElement("div");
    div.innerHTML = html;
    return Array.from(div.querySelectorAll("h2, h3")).map((h) => ({ id: h.id, text: h.textContent || "", level: h.tagName === "H2" ? 2 : 3 }));
  }, [html, guide]);
  useEffect(() => {
    if (guide && loc.hash) document.getElementById(decodeURIComponent(loc.hash.slice(1)))?.scrollIntoView();
    else if (guide) window.scrollTo(0, 0);
  }, [guide, loc.hash]);
  const list = (query ? index.data?.guides : all.data?.guides) || [];
  const cats = all.data?.categories || [];
  const siblings = all.data?.guides.filter((g) => g.category === guide?.category) || [];
  const pos = siblings.findIndex((g) => g.slug === guide?.slug);
  const nav = (
    <>
      <input type="search" aria-label="Search the documentation" placeholder="Search the documentation" value={q} onChange={(e) => setQ(e.target.value)} />
      {(index.loading && !index.data) ? <Skeleton /> : query ? (
        <ul className="plain help-results">{list.map((g) => <li key={g.slug}><Link to={`/help/${g.slug}`}>{g.title}</Link>{g.excerpt && <div className="small muted">…{g.excerpt}…</div>}</li>)}
          {!list.length && <li className="muted small">No guide mentions “{query}”.</li>}</ul>
      ) : cats.map((c) => {
        const items = list.filter((g) => g.category === c);
        if (!items.length) return null;
        return <div key={c} className="help-cat"><h3>{c}</h3><ul className="plain">{items.map((g) => <li key={g.slug}><Link to={`/help/${g.slug}`} className={g.slug === slug ? "active" : ""} aria-current={g.slug === slug ? "page" : undefined}>{g.title}</Link></li>)}</ul></div>;
      })}
    </>
  );
  return (
    <div className="help-layout docs">
      <aside className="card help-nav" aria-label="Documentation">
        <h2>Help & documentation</h2>
        <details className="help-nav-mobile" onToggle={(e) => setNavOpen((e.currentTarget as HTMLDetailsElement).open)}><summary>Browse guides</summary>{navOpen && nav}</details>
        <div className="help-nav-desktop">{nav}</div>
        <p className="small muted">Personal Documents Management System {all.data?.version} by Atik Ansari. The guides are bundled with the app and match this version.</p>
      </aside>
      <article className="card markdown help-article">
        {!slug ? (
          <>
            <h1>Help & documentation</h1>
            <p>Step-by-step guides with screenshots for the features you can use. <HelpTip id="help.permissions" /></p>
            <div className="help-start">
              {[["getting-started", "Getting started", "home"], ["backup-restore", "Backup & Recovery", "db"], ["disaster-recovery", "Disaster recovery runbook", "refresh"],
                ["notifications", "Notifications", "bell"], ["security-map", "Sign-in security & Trusted Zones", "shield"], ["troubleshooting", "Troubleshooting", "help"]]
                .filter(([s]) => all.data?.guides.some((g) => g.slug === s)).map(([s, t, i]) =>
                <Link key={s} to={`/help/${s}`} className="help-tile"><Icon name={i} /> {t}</Link>)}
            </div>
          </>
        ) : guide ? (
          <>
            <nav className="breadcrumbs small" aria-label="Breadcrumb"><Link to="/help">Help</Link> <span aria-hidden="true">›</span> <span>{guide.category || "Guides"}</span> <span aria-hidden="true">›</span> <span aria-current="page">{guide.title}</span></nav>
            {toc.filter((t) => t.level === 2).length > 2 && (
              <nav className="toc" aria-label="On this page"><strong className="small">On this page</strong>
                <ul className="plain">{toc.filter((t) => t.level === 2).map((t) => <li key={t.id}><a href={`#${t.id}`}>{t.text}</a></li>)}</ul></nav>
            )}
            <div dangerouslySetInnerHTML={{ __html: html }} />
            <footer className="help-foot small muted">
              {guide.reviewed && <span>Last reviewed {guide.reviewed}. </span>}
              <span className="row" style={{ gap: 12, justifyContent: "space-between", flexWrap: "wrap" }}>
                {pos > 0 ? <Link to={`/help/${siblings[pos - 1].slug}`}>‹ {siblings[pos - 1].title}</Link> : <span />}
                {pos >= 0 && pos < siblings.length - 1 ? <Link to={`/help/${siblings[pos + 1].slug}`}>{siblings[pos + 1].title} ›</Link> : <span />}
              </span>
            </footer>
          </>
        ) : <Skeleton lines={10} />}
      </article>
    </div>
  );
}
