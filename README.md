# Digital Service Pakistan Employee App

Python desktop app prototype for employee attendance, break tracking, sold item entry, local 5-day sales review, and Excel workbook row sync.

## Run Locally

```powershell
pip install -r requirements.txt
python main.py
```

Set private credentials locally before first use. Do not commit real passwords to GitHub.

```powershell
$env:DSP_DEFAULT_PASSWORD="your-employee-password"
$env:DSP_ADMIN_PASSWORD="your-admin-password"
$env:DSP_RESET_CODE="your-private-reset-code"
python main.py
```

If these environment variables are not set on first run, the app generates local bootstrap credentials in the app data folder. Keep that file private and rotate the password from inside the app.

The public repository must not contain local files from `data/`, `auth_config.json`, `bootstrap_credentials.txt`, `.env`, or real Excel workbooks. These are ignored by `.gitignore`.

## Current Scope

This first version builds a polished, modular UI and local screen flow:

- Login and password reset
- Admin-managed registered employees with freeze, edit, reset-password, and remove actions
- Separate admin panel login
- Auto logout on app close
- Attendance day start / end
- Attendance check in / check out
- First-shift close and second/night-shift tracking on the same day
- Break start / end
- Employee Notes section with daily notes and permanent notes saved in SQLite
- Admin attendance sheet with shift summaries and event timeline
- Admin-to-employee announcements
- Admin-managed client message templates for services such as Capcut, Adobe, and VPN
- Admin sales workbook target settings
- Sold item entry form matching the owner workbook columns
- Numeric-only buying and selling amount fields
- Auto-filled, read-only sales date field
- `Other` status reason field that saves the typed reason as the final status
- Local saved sales entries for the last 5 calendar days so accidental close does not wipe recent work
- Excel sales row sync for the mapped owner workbook columns
- Employee-facing sales numbering resets every day (`#1`, `#2`, etc. per date)
- 5-day day-card selector with a focused entries table for the selected date
- Edit recent entries without employee delete access

## Employee Notes

The employee dashboard includes a `Notes` section with two notepad-style areas:

- `Daily Notes` are saved by employee and date, so each day can have its own note and older daily notes remain available from the saved notes list.
- `Permanent Notes` are saved as one long-running note per employee for must-remember details.

Both note types are stored locally in SQLite and stay available after restarting the app.

## Updates With GitHub Releases

The app checks the configured GitHub repository's latest release after login:

```text
https://github.com/ZerO4837/Employee-Management
```

If the latest release tag is newer than `APP_VERSION` in `app/config.py`, the employee sees an update prompt. Choosing update closes the app, downloads the release asset, applies it, and reopens the app automatically.

Release asset support:

- `.zip`: extracted over the app folder while keeping local `data/`, `.env`, auth files, and Git metadata untouched.
- `.exe`: downloaded and run as an installer/updater.
- `.msi`: downloaded and run with `msiexec /i`.

For each update:

1. Increase `APP_VERSION` in `app/config.py`.
2. Build/package the app update.
3. Create a GitHub Release with a higher tag, such as `v0.1.1`.
4. Upload one update asset (`.zip`, `.exe`, or `.msi`) to that release.

If update installation fails, the app writes `update_error.log` locally and still reopens.

## Security Notes

Anyone can download a public repository, so do not store real passwords, reset codes, OneDrive workbook URLs, or local SQLite data in GitHub. The application code alone cannot write to your business workbook unless that computer also has the workbook target/settings and valid OneDrive access.

Authentication data is stored locally in `auth_config.json` using password hashes. New hashes use PBKDF2; older SHA-256 hashes are upgraded after a successful login.

The admin panel's `Registered Employees` tab can add employees, edit their name/username/status, freeze accounts, reset passwords, and remove employees. Existing passwords are not displayed because they are stored as hashes; when an admin creates or resets a user, the newly generated/entered password is shown at that moment.

## Sales Excel Sync

The sold item form now matches the owner workbook columns:

```text
A Customer Name
B Items Sold
C Email/Order ID
D Buying Amount
E Selling Amount
F Profit (=Erow-Drow)
G Status
H Date (auto-filled as day/month/year)
```

If Status is set to `Other`, the app opens an extra reason field and writes that reason into column G.

The Items Sold field uses a preset service dropdown. Selecting `Other` opens an extra service-name field.

Two shared-screen services have special account-fill behavior:

- `Netflix Screens` uses a maximum of 5 customer names per same Email/Order ID.
- `HBO Max Screen` uses a maximum of 9 customer names per same Email/Order ID.

When one of those services is sold again with the same Email/Order ID, the Excel sync updates the existing workbook row instead of creating a new row. The new customer name is appended to column A with a comma, and the new Selling Amount is added into that row. Buying Amount stays unchanged on the account row. If the account is already full, the employee sees a warning to use a new account email.

If a Netflix/HBO customer name is edited from the 5-Day Data screen, Excel replaces the previous name in that comma-separated customer list instead of adding another customer.

New entries are saved locally first, then copied into the workbook in the background so the employee form does not freeze while Excel opens and saves the OneDrive file. By default, source runs write to:

```text
data/sales_entries.xlsx
```

Each new entry opens the current workbook and finds the next append row at that moment. The scan treats rows with real sales-entry data in Customer, Items Sold, Email/Order ID, Buying Amount, Selling Amount, or Status as occupied. Formula/date-only rows, such as pre-filled Profit formulas or prepared dates, are treated as empty so they do not push new sales far below the real data.

Employee-facing entry numbers are display numbers only. They reset every date, so if yesterday has `#1` and `#2`, today's first sale shows as `#1`. The hidden database ID is still kept internally so editing and Excel sync can safely update the correct record.

The employee app keeps a rolling 5-day local sales view:

- The Sold Item Entry page shows today's count only.
- The 5-Day Data page shows one clickable date card for each of the last 5 calendar days.
- Clicking a date card opens only that date's entries in the table.
- Synced local entries older than the 5-day employee window stay in the local database for admin month views.
- Unsynced old entries are kept locally to avoid losing sales if Excel sync failed.
- Excel remains the main permanent sales record.

The admin panel has a `Sales Data` tab that shows sales records across employees, including totals and Excel sync status. Admin can switch between `Last 5 Days` and current-year month sections such as `January Sales`, `February Sales`, and so on. These month choices reset naturally when the year changes.

If Excel reports that a Netflix/HBO screen account is already full, the app removes that unsynced local retry row instead of keeping it as `Retry needed`.

To connect your real OneDrive workbook, set this environment variable before starting the app:

```powershell
$env:DSP_SALES_WORKBOOK_PATH="C:\Users\YOUR_USER\OneDrive\Path\To\YourWorkbook.xlsx"
python main.py
```

Optional: set `DSP_SALES_WORKSHEET_NAME` if the data should go to a specific worksheet. If it is empty, the first active sheet is used.

The admin panel can also change the active workbook without editing code:

1. Log in with the admin account.
2. Use `Browse` to select an existing `.xlsx` or `.xlsm` workbook path. For OneDrive sync, browse to the synced OneDrive file itself.
3. Optionally enter a worksheet name.
4. Click `Save Target`.

`Upload Workbook` copies a workbook into the app data folder for local-only use. For the owner OneDrive workflow, prefer `Browse` so the app writes directly to the synced cloud file.

Close the workbook in Excel before employee entries are saved. If Excel has the file open, Windows may lock it and the app will keep the entry locally until the workbook can be written.

If an entry is saved locally but Excel sync fails, the employee can open 5-Day Data, select that failed row, and use `Sync Again With Excel` after the workbook is available.

If the employee tries to close the app while Excel sync is still running, the app waits for the active background sync queue to finish and then closes automatically. If Excel sync fails during that attempt, the entry still stays saved locally and can be retried from 5-Day Data.

On Windows OneDrive workbook paths, the app uses Microsoft Excel in the background for saving. This avoids OneDrive file-handle errors that can happen when writing synced workbooks directly with `openpyxl`.

If Excel shows two recent files with the same name, prefer the direct Socio Digital cloud workbook URL (`https://d.docs.live.net/...`) as the app target instead of the downloaded/local copy path. That keeps new entries going to `Socio Digital's OneDrive > Documents > Data 2026`.

To get the direct workbook URL for a new month:

1. Open the new month workbook from `Socio Digital's OneDrive` in the Excel desktop app.
2. In Excel, go to `File` -> `Info`.
3. Click `Copy Path`.
4. Paste that value into the admin panel Sales Workbook target.
5. If the copied value has anything after `.xlsx` or `.xlsm`, remove the extra part so it ends exactly with the workbook extension.

Do not paste a OneDrive browser sharing URL into the workbook field. `https://1drv.ms/...` links open a web page; they are not writable workbook file paths for `openpyxl`.

The employee only sees the app UI. If the employee PC has no OneDrive login and no workbook file access, direct Excel writing from that employee PC cannot reach your private OneDrive workbook by itself. For strict no-workbook-access with two separate PCs, use a shared database/API queue where the employee app submits sales and the owner/admin side writes them into Excel using your credentials or your local OneDrive sync.

## Project Structure

```text
main.py                 App launcher
app/config.py           Business settings, paths, colors, and form field definitions
app/auth.py             Login and password reset storage
app/storage.py          SQLite attendance, announcements, sales, and app settings storage
app/excel_sales.py      Excel workbook row writer for sold item entries
app/utils.py            Date, money, and duration formatting helpers
app/main_app.py         Main Tkinter window and page routing
app/ui/widgets.py       Shared high-fi widgets, gradient elements, cards, buttons
app/ui/login.py         Login screen
app/ui/reset_password.py Password reset screen
app/ui/dashboard.py     Dashboard, attendance, sold item, and 5-day sales data screens
app/ui/admin.py         Owner/admin attendance, announcements, and sales workbook panel
assets/logo.jpeg        Business logo
assets/app_icon.ico     Windows app/taskbar/exe icon
```

## Attendance Flow

Employee attendance is tracked as a day with shifts inside it:

```text
Start Day -> Check In -> Close First Shift -> Check In -> Check Out -> End Day
```

The night shift stays attached to the same attendance day until `End Day` is clicked.

## Close And Reopen Behavior

If the app is closed by mistake, the in-memory login session is cleared. Reopening the app always starts at the login screen.

Saved local work is restored after login:

- Active attendance day
- Active shift/check-in state
- Break state
- Last 5 days of sold item entries
- Employee announcements

## Announcements

The admin panel can send announcements to the employee dashboard. Use this for service availability, out-of-stock notices, urgent reminders, or general updates.

Employee notifications appear in the header notification control:

- Unread announcements show a count badge.
- Clicking notifications opens a bubble-style dropdown inside the employee dashboard.
- Marking notifications as read clears the badge.
- Announcements stay visible for 3 days, then disappear automatically.
- The admin send action uses a branded in-app alert instead of a native Windows popup.

Announcements are saved locally in SQLite and can also sync through Supabase Cloud Sync, so admin messages sent from one PC can appear on employee PCs.

## Client Message Templates

The admin panel includes a Service Messages section for approved, pre-formatted client replies. Each saved message uses the service/category as its label and keeps the full message body. Emoji, line breaks, links, and spacing are saved as typed. Existing service messages can be edited or deactivated from the same panel.

The employee dashboard includes a Client Messages view where active service messages can be filtered by service, previewed, and copied to the clipboard for sending to clients.

## Owner App / Employee App Direction

Do not split this into two unrelated projects. Keep one codebase and one shared data design, then package different access modes later:

- Employee mode: employee login, attendance, breaks, sold item entry.
- Admin mode: owner login, attendance sheet, shift timeline, future reports.

For two different PCs to stay linked, the next step will be one shared sync layer, such as a small cloud database/API, a private local-network server, or a controlled shared workbook location. The current SQLite layer gives the app a professional local data foundation, but SQLite by itself is not a live multi-PC sync system.

## Supabase Scope

Supabase is currently used for registered employee accounts, attendance records, the Items Sold list, inventory credentials, admin-controlled announcements, and service message templates. Notes, sales entries, and Excel sync still use the local app database/OneDrive workflow unless you decide to move those online later.

Do not put the Supabase `service_role` key inside the desktop app, public repository, or packaged `.exe`.

## Future EXE Packaging Notes

The project is ready to package later with a tool such as PyInstaller. The app now separates bundled assets from writable data:

- `assets/` is read-only app content and should be bundled into the `.exe`.
- `data/` is used only while running from source and is ignored by Git. Do not include the local `data/` folder in the public release or installer.
- In a packaged Windows `.exe`, login/reset data, local sales records, notes, cloud settings, and the managed workbook cache are stored in the employee user's local app data folder: `%LOCALAPPDATA%\Digital Service Pakistan\Employee Management`.
- Updates should replace only application files. Do not delete or overwrite `%LOCALAPPDATA%\Digital Service Pakistan\Employee Management`, otherwise employee records and offline cache will be reset.
- The built-in zip updater also skips SQLite/database files, `supabase_config.json`, and workbook files if they appear in an update package by mistake.

Example PyInstaller shape for later:

```powershell
pyinstaller --noconsole --name "Digital Service Pakistan Employee" --icon "assets/app_icon.ico" --add-data "assets;assets" main.py
```

## Supabase Cloud Sync

The app now supports Supabase sync for registered employee accounts, attendance records, the Items Sold list, inventory credentials, admin announcements, and service message templates, so different PCs can share admin-to-employee updates and the admin PC can see employee attendance.

The admin panel includes an Items Sold List tab. Add, rename, or remove services there to control the employee Sold Item Entry dropdown without editing code.

1. Create/open a Supabase project.
2. Open `supabase_schema.sql` in this repo.
3. Replace `CHANGE_THIS_ADMIN_SECRET` with a strong private phrase that only the admin PC will know.
4. Replace `CHANGE_THIS_EMPLOYEE_SYNC_SECRET` with a different private phrase used by installed employee apps to pull account updates.
5. Run the SQL in Supabase Dashboard > SQL Editor.
6. In Supabase Dashboard, copy the Project URL and anon public key from the API/Data API settings.
7. In the app, log in as admin and open Admin > Cloud Sync.
8. Enable cloud sync, paste the Project URL, anon public key, admin write secret, and employee sync secret, then save.
9. On employee PCs, use the same Project URL, anon key, and employee sync secret. Do not give employees the admin write secret.

The anon key is only used directly for low-risk read sync such as announcements and service message templates. Employee account sync, Items Sold list sync, and inventory sync go through Supabase RPC functions that also require the employee sync secret, and admin writes go through RPC functions that require the admin write secret. Do not put the Supabase `service_role` key inside the app, the repository, or the packaged installer.

Employee passwords are never synced as plain text. The cloud user sync sends the protected password hash so installed employee apps can verify login locally. Inventory passwords are synced because employees need to view and copy them, so keep the employee sync secret private and only include it in trusted installed copies.

The app still keeps SQLite as an offline cache. If Supabase is unavailable, employees can keep using local app data and the cloud sync will retry in the background when the app is open.
