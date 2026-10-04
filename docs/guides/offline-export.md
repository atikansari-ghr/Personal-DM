# Offline use and exports

## Saving files for offline use {#offline}

People with download permission can open a document and choose **Save for offline use**. Nothing is stored offline unless you choose it — simply viewing a document does not cache it.

The **Offline files** page shows saved files, their size, browser storage use, and lets you open or remove them. Use **Protect storage** to ask the browser not to clean up the files automatically; browsers may refuse.

### Limits {#limits}

Browsers limit how much they store, and may delete data when the device is low on space. Large libraries (for example 10 GB) will usually not fit on a phone. Use the export below instead.

### Privacy on shared devices {#privacy}

- Offline files belong to the account that saved them and are never listed for another account.
- By default they are **deleted when you sign out**. You can choose to keep them on a device you trust.
- When you reconnect, the app asks the server which files you may still access and deletes revoked ones. While a device stays offline, revocation cannot take effect.
- Saving and removing offline files is recorded in the audit log (best effort).

## Exporting your library {#export}

**Offline files → Export my whole library** downloads every document you can download, in its folder structure, as one or more ZIP parts (512 MB, 2 GB or 4 GB). Each part contains `MANIFEST.json` and `SHA256SUMS.txt` for checking integrity. The export is streamed, so the server does not need extra disk space to build it.

A single folder (for example a DICOM study) can be downloaded with **Download folder (ZIP)**.

Exported files are outside the app: their use cannot be tracked or revoked.
