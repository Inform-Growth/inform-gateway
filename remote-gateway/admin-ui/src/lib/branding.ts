// The literal strings on the right are Jinja templates that Copier renders at
// `copier copy` time. On the template branch itself (no Copier render), the
// strings remain raw (e.g. "[[ project_name ]]") — the fallback below detects
// that and substitutes generic defaults so local template-branch dev shows
// readable text instead of the literal placeholder syntax.
const TPL_NAME  = "[[ project_name ]]";
const TPL_TITLE = "[[ admin_ui_title ]]";

const looksUnrendered = (s: string) => s.startsWith("[[");

export const BRAND_NAME    = looksUnrendered(TPL_NAME)  ? "Gateway"       : TPL_NAME;
export const BRAND_TAGLINE = looksUnrendered(TPL_TITLE) ? "Gateway Admin" : TPL_TITLE;
