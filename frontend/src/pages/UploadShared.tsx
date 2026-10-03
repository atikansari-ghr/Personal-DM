import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import UploadDialog from "../components/UploadDialog";

// Receives files shared from the OS share sheet (stored by the service worker), or explains the fallback.
export default function UploadShared() {
  const nav = useNavigate();
  const [files, setFiles] = useState<File[] | null>(null);
  useEffect(() => {
    (async () => {
      if (typeof caches === "undefined") return setFiles([]);
      const cache = await caches.open("pd-share-inbox");
      const keys = await cache.keys();
      const out: File[] = [];
      for (const k of keys) {
        const res = await cache.match(k);
        if (res) out.push(new File([await res.blob()], decodeURIComponent(res.headers.get("X-Filename") || "shared-file"), { type: res.headers.get("Content-Type") || "" }));
        await cache.delete(k);
      }
      setFiles(out);
    })();
  }, []);
  if (files === null) return null;
  if (!files.length)
    return (
      <div className="card stack">
        <h1>Upload from your phone</h1>
        <p>Your device did not share any files with the app. Some phones (notably iPhone) do not support sharing files into web apps.</p>
        <p>Instead: open <strong>Upload</strong> and choose <em>Choose files</em> (Files or Photos) or <em>Take photo</em>.</p>
        <button className="btn primary" onClick={() => nav("/folders")}>Go to folders</button>
      </div>
    );
  return <UploadDialog initialFiles={files} onClose={() => nav("/")} onDone={() => nav("/")} />;
}
