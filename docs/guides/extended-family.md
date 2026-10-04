# Extended family, permissions and delegation

## Family groups {#groups}

Groups organise people, for example *My family*, *Grandparents*, *Uncle's family*. Each group can have a **head**, who receives that group's expiry reminders. Being a member, a head or a relative never grants access to documents by itself.

Each person has one **reminder group** (Settings → Family & access → Edit member). Changing a group's head changes who receives future reminders only.

## Capabilities {#capabilities}

| Capability | Allows |
|---|---|
| View | See and preview documents, text and details |
| Download | Download, export and save offline |
| Upload | Add new documents |
| Edit | Change titles, types, tags and details |
| Version | Upload a better scan as a new version |
| Organise | Create, rename and move folders |
| Archive | Archive (the app's "delete") |
| Share | Create public links |
| Manage | Change permissions |

## How access is decided {#inheritance}

1. The main administrator can do everything.
2. Rules on a folder apply to everything inside it (subfolders and documents) — this is *inheritance*.
3. You can turn inheritance off for a subfolder or a single document; then only the rules placed directly on it apply. This is how exceptions are made.
4. Without a rule, the answer is **no access**.
5. Archived items are visible only to the main administrator.

Open a folder or document and choose **Who has access** to see the rules, grant access to a person or a whole group, and check *why* someone has access.

## Delegation {#delegation}

The main administrator can give a person scoped administration over one group:

| Scope | Effect |
|---|---|
| Manage documents | View, download, upload, edit and organise documents of the group's members |
| Group membership | Add or remove members of that group |
| Folder permissions | Grant access on the members' folders — only capabilities the delegate holds, never *Manage* |
| Reminders | Manage reminders for the group |
| Receive reminders | Receive expiry reminders for the group's members |

Protections: delegates can never grant more than they hold, cannot create delegations, and cannot add people to a group that holds access the delegate lacks. Moving a folder that inherits access requires *Manage*, so moves cannot be used to leak documents.

## Reminder recipients and access {#reminders-vs-access}

Receiving a reminder does not grant access: the link in a reminder still requires sign-in and view permission. If a head cannot view a person's documents, they receive only the minimal reminder (name, type, date).
