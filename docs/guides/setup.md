# Family accounts and first-run setup

## One-time setup code {#setup-code}

The setup wizard is locked until you enter a one-time code printed on the server console:

```
sudo personaldocs setup-token
```

The code is valid for 24 hours and stops working after setup completes, so nobody on the internet can claim your installation.

## The Main Administrator {#main-admin}

Setup creates **one account only: the Main Administrator** (you). Enter your name, username and password; email and a relationship label (for example *Father*) are optional. You become the head of the initial family group. No other accounts, placeholder members or default names are created.

## Adding family members (optional) {#add-members}

The next step, **Add family members (optional)**, lets you add zero, one or many people right away:

- **Add a family member** adds a row: name, username, relationship (suggestions such as Mother, Son or Daughter, or type your own), optional email and an optional password. Leave the password empty to get a generated temporary password, shown once at the end.
- **Remove** deletes a row before it is saved. **Skip for now** continues without members.
- Members must change their temporary password at first sign-in.

You can always add people later in **Settings → Family & access → Add member**. Rerunning setup is refused once it has completed, so accounts are never duplicated. Names, usernames and emails can be edited later without breaking anything, because every account has a permanent internal ID.

### Upgrading an installation created by an earlier release {#six-accounts}

Earlier releases created six default family accounts during setup. Upgrading **keeps every existing account, folder and document**; nothing is deleted or renamed. Accounts you no longer need can be deactivated in Settings → Family & access. Deactivating or removing a person never silently deletes their documents: the documents stay in their library, where the administrator can move them.

### Names in screenshots {#demo-names}

The public screenshots use the labels *A. Ansari* (administrator), *Mom*, *Son1*, *Son2*, *Son3* and *Daughter*. They are demonstration accounts added in the optional step for the pictures; they are not defaults, and the application never creates them.

## What each person sees initially {#initial-access}

Each person gets a personal folder. Only that person and the main administrator can see it. Nothing is shared automatically: grant access per folder (see [Extended family and delegation](extended-family.md)). The wizard can optionally let the family group view the "Shared family" folder.

## Accounts for everyone {#everyone}

Every person whose documents are managed — including grandparents and young children — has their own account, even if they never sign in. The administrator can manage their documents before they first sign in. There is no public registration.
