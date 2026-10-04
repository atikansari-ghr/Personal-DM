# Family accounts and first-run setup

## One-time setup code {#setup-code}

The setup wizard is locked until you enter a one-time code printed on the server console:

```
sudo personaldocs setup-token
```

The code is valid for 24 hours and stops working after setup completes, so nobody on the internet can claim your installation.

## The six initial accounts {#six-accounts}

| Role label | Suggested username | Initial responsibility |
|---|---|---|
| Dad | dad | Main administrator and head of the initial family group |
| Mom | mom | Family member |
| Son1 | son1 | Family member |
| Daughter | daughter | Family member |
| Son2 | son2 | Family member |
| Son3 | son3 | Family member |

Enter each person's real name. Role labels describe relationships and can be changed. Names, usernames and emails can be edited later without breaking anything, because every account has a permanent internal ID.

- Dad sets his own password. Other members get an individually generated temporary password (shown once) or one you type; they must change it at first sign-in.
- Leave a member's name empty to skip that slot; add the person later in Settings → Family & access.
- Rerunning setup is refused once it has completed, so accounts are never duplicated.

## What each person sees initially {#initial-access}

Each person gets a personal folder. Only that person and the main administrator can see it. Nothing is shared automatically: grant access per folder (see [Extended family and delegation](extended-family.md)). The wizard can optionally let the family group view the "Shared family" folder.

## Accounts for everyone {#everyone}

Every person whose documents are managed — including grandparents and young children — has their own account, even if they never sign in. The administrator can manage their documents before they first sign in. There is no public registration.
