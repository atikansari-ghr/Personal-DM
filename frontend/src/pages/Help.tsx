import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api } from "../api";
import { renderMarkdown, Skeleton, useAsync } from "../components/ui";

export default function HelpPage() {
  const { slug } = useParams();
  const loc = useLocation();
  const [q, setQ] = useState("");
  const index = useAsync(() => api<{ guides: { slug: string; title: string; excerpt?: string }[]; version: string }>("help", { query: { q } }), [q]);
  const [guide, setGuide] = useState<{ title: string; markdown: string } | null>(null);
  useEffect(() => {
    setGuide(null);
    if (slug) api(`help/${slug}`).then(setGuide).catch(() => setGuide({ title: "Not found", markdown: "# Not found\nThis guide does not exist." }));
  }, [slug]);
  useEffect(() => {
    if (guide && loc.hash) document.getElementById(loc.hash.slice(1))?.scrollIntoView();
  }, [guide, loc.hash]);
  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(220px, 300px) 1fr", alignItems: "start" }}>
      <aside className="card">
        <h2>Help & guides</h2>
        <input type="search" aria-label="Search help" placeholder="Search help" value={q} onChange={(e) => setQ(e.target.value)} />
        {index.loading && !index.data ? <Skeleton /> : (
          <ul style={{ paddingLeft: "1rem" }}>
            {index.data?.guides.map((g) => <li key={g.slug}><Link to={`/help/${g.slug}`}>{g.title}</Link>{g.excerpt && <div className="small muted">…{g.excerpt}…</div>}</li>)}
          </ul>
        )}
        <p className="small muted">Version {index.data?.version}. All guides are bundled with the app.</p>
      </aside>
      <article className="card markdown">
        {!slug ? (
          <><h1>Help</h1><p>Choose a guide on the left, or start with <Link to="/help/getting-started">Getting started</Link>.</p></>
        ) : guide ? <div dangerouslySetInnerHTML={{ __html: renderMarkdown(guide.markdown) }} /> : <Skeleton lines={10} />}
      </article>
    </div>
  );
}
