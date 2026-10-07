export interface UserMini {
  id: string;
  display_name: string;
  initials: string;
  avatar_color: string;
  photo_version?: string | null;
}
export interface User extends UserMini {
  role_label: string;
  is_main_admin: boolean;
  is_admin?: boolean;
  is_active: boolean;
  is_head: boolean;
  username?: string;
  full_name?: string;
  email?: string;
  must_change_password?: boolean;
  totp_enabled?: boolean;
  last_login?: string | null;
  reminder_group?: string | null;
  groups?: string[];
  google_linked?: boolean;
  authentik_linked?: boolean;
  passkey_count?: number;
  passwordless_enabled?: boolean;
  two_factor_setup_required?: boolean;
}
export interface Session {
  setup_complete: boolean;
  app_name: string;
  login?: import("./pages/Auth").LoginBranding;
  version: string;
  google_enabled: boolean;
  authentik?: { enabled: boolean; label: string; show_logo: boolean };
  pending_2fa: boolean;
  pending_methods?: string[];
  passkeys_enabled?: boolean;
  passwordless_enabled?: boolean;
  totp_allowed?: boolean;
  user: User | null;
  preferences?: { theme: string; layout: string; dashboard_widgets: string[]; overview_layout?: Record<string, WidgetCfg>; doc_view?: string; doc_sort?: string };
  date_format?: string;
  timezone?: string;
  delegations?: { group: string; group_id: string; scopes: string[] }[];
}
export interface Expiry {
  days: number | null;
  label: string;
  level: "ok" | "soon" | "expired" | "none";
}
export interface DocRow {
  id: string;
  title: string;
  folder: string;
  owner: UserMini;
  type: { id: number; name: string; emoji?: string; confirmed?: boolean } | null;
  type_suggested?: boolean;
  state: string;
  expiry_date: string | null;
  issue_date: string | null;
  expiry: Expiry | null;
  ocr_state?: string;
  av_status?: string | null;
  created_at: string;
  archived: boolean;
  size: number | null;
  format: string | null;
  file_kind: string;
  file_label: string;
  has_thumbnail: boolean;
  version_id: string | null;
  caps: string[];
  snippet?: string;
}
export interface Version {
  id: string;
  antivirus?: { status: string; signature: string; engine: string; detail: string; scanned_at: string | null; blocked: boolean; released_at: string | null };
  number: number;
  original_name: string;
  size: number;
  sha256: string;
  mime: string;
  format: string;
  file_kind: string;
  file_label: string;
  comment: string;
  state: string;
  error: string;
  ocr_applied: boolean;
  ocr_pages?: string;
  is_additional?: boolean;
  ocr_quality: { confidence: number; rotation: number; skew: number; steps: string[]; low_lines: number[]; line_count: number } | null;
  pdfa: boolean;
  pdfa_check: { validator: string; profile: string; compliant: boolean; full_validation: boolean; failed_rules: { description: string; clause?: string }[]; note?: string } | null;
  page_count: number | null;
  has_preview: boolean;
  has_thumbnail: boolean;
  created_at: string;
  created_by: string | null;
}
export interface Field {
  key: string;
  value: string;
  sensitive: boolean;
  label?: string;
  status: "proposed" | "confirmed";
  source: string;
  source_label?: string;
  scope?: "type" | "custom" | "unmapped";
  group?: "template" | "additional" | "unmapped";
  overridden?: boolean;
  previous_type?: string;
  confidence: number | null;
  flags: string[];
  excerpt: string;
  proposed_value: string;
  confirmed_at: string | null;
  updated_at?: string | null;
  confirmed_by?: string | null;
}
export interface TemplateField {
  key: string;
  label: string;
  field_type: string;
  required: boolean;
  help_text: string;
  choices: string[];
  role: string;
  sensitive?: boolean;
}
export interface TypeSuggestion { index: number | null; type: number; name: string; source: string; source_label: string; reason: string; confidence: number | null; conflict?: boolean }
export interface DetailsStatus { status: "confirmed" | "incomplete" | "needs_review" | "empty"; proposed: number; unmapped: number; missing_required: string[]; incomplete_ok: boolean }
export interface DocDetail extends DocRow {
  ocr?: { state: string; mode: string; sources: { version: string; pages: string }[]; languages: string[]; error: string; ai_allowed: boolean };
  title_is_custom: boolean;
  correspondent: { id: number; name: string } | null;
  tags: { id: number; name: string; color: string }[];
  review_flags: string[];
  inherit_permissions: boolean;
  fields: Field[];
  template: TemplateField[];
  type_info: { source: string; source_label: string; confirmed: boolean; suggestions: TypeSuggestion[] };
  details_status: DetailsStatus;
  can_manage_types: boolean;
  versions: Version[];
  current_version: Version | null;
  path: { id: string; name: string; emoji: string }[];
  renews: { id: string; title: string } | null;
  renewed_by: { id: string; title: string }[];
  source_path: string;
  history: { at: string; action: string; changes: any; actor: string | null }[];
  archived_at: string | null;
}
export interface FolderNode {
  id: string;
  parent: string | null;
  name: string;
  emoji: string;
  emoji_is_custom: boolean;
  kind: string;
  owner: string | null;
  inherit_permissions: boolean;
  caps: string[];
  path_only: boolean;
  count: number;
  archived: boolean;
  owner_user: UserMini | null;
  suggested_type?: { id: number; name: string } | null;
}
export interface Group {
  id: string;
  name: string;
  head: string | null;
  members: string[];
  delegations: { delegate: string; scopes: string[] }[];
}
export interface Meta {
  types: { id: number; name: string; template: string; has_expiry: boolean; emoji?: string; archived?: boolean; description?: string }[];
  tags: { id: number; name: string; color: string }[];
  correspondents: { id: number; name: string }[];
  fields: { key: string; label: string; type: string; choices: string[] }[];
  templates: string[];
  standard_fields: string[];
}

export interface WidgetCfg { w?: number; style?: "rect" | "compact" | "circle" | "compact_circle"; settings?: Record<string, any> }
