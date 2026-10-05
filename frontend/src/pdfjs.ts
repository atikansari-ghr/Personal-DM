// Loaded on demand by the document viewer (keeps PDF.js out of the main bundle).
// The legacy build supports the older Safari/Chrome versions still common on family phones.
import * as pdfjs from "pdfjs-dist/legacy/build/pdf.mjs";
import workerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export type PdfDoc = Awaited<ReturnType<typeof pdfjs.getDocument>["promise"]>;

export function openPdf(data: ArrayBuffer): Promise<PdfDoc> {
  return pdfjs.getDocument({
    data,
    isEvalSupported: false, // the app's CSP forbids eval; never needed for rendering
    enableXfa: false,
    standardFontDataUrl: `${__PDFJS_ASSETS__}standard_fonts/`,
    cMapUrl: `${__PDFJS_ASSETS__}cmaps/`,
    cMapPacked: true,
    wasmUrl: `${__PDFJS_ASSETS__}wasm/`,
    iccUrl: `${__PDFJS_ASSETS__}iccs/`,
  } as any).promise;
}
