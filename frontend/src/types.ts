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
}
export interface Session {
  setup_complete: boolean;
  app_name: string;
  version: string;
  google_enabled: boolean;
  pending_2fa: boolean;
  user: User | null;
  preferences?: { theme: string; layout: string; dashboard_widgets: string };
  date_format?: string;
  timezone?: string;
  delegations?: { group: string; group_id: string; scopes: string[] }[];
}
export interface Expiry {
  days: number;
  label: string;
  level: "ok" | "soon" | "expired";
}
export interface DocRow {
  id: string;
  title: string;
  folder: string;
  owner: UserMini;
  type: { id: number; name: string } | null;
  state: string;
  expiry_date: string | null;
  issue_date: string | null;
  expiry: Expiry | null;
  created_at: string;
  archived: boolean;
  size: number | null;
  format: string | null;
  has_thumbnail: boolean;
  version_id: string | null;
  caps: string[];
  snippet?: string;
}
export interface Version {
  id: string;
  number: number;
  original_name: string;
  size: number;
  sha256: string;
  mime: string;
  format: string;
  comment: string;
  state: string;
  error: string;
  ocr_applied: boolean;
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
  status: "proposed" | "confirmed";
  source: string;
  confidence: number | null;
  flags: string[];
  excerpt: string;
  proposed_value: string;
  confirmed_at: string | null;
}
export interface DocDetail extends DocRow {
  title_is_custom: boolean;
  correspondent: { id: number; name: string } | null;
  tags: { id: number; name: string; color: string }[];
  review_flags: string[];
  inherit_permissions: boolean;
  fields: Field[];
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
}
export interface Group {
  id: string;
  name: string;
  head: string | null;
  members: string[];
  delegations: { delegate: string; scopes: string[] }[];
}
export interface Meta {
  types: { id: number; name: string; template: string; has_expiry: boolean }[];
  tags: { id: number; name: string; color: string }[];
  correspondents: { id: number; name: string }[];
  fields: { key: string; label: string; type: string; choices: string[] }[];
  templates: string[];
  standard_fields: string[];
}
