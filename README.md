# Digital Service Pakistan Employee App

Python desktop app prototype for employee attendance, break tracking, sold item entry, local 5-day sales review, and Excel workbook row sync.

## Run Locally

```powershell
pip install -r requirements.txt
python main.py
```

Default login:

```text
Username: masabiha
Password: Employee@7260
```

Admin login:

```text
Username: KillerPanel
Password: Compiler@Panel@675
```

Forgot-password private code:

```text
2004212802
```

## Current Scope

This first version builds a polished, modular UI and local screen flow:

- Login and password reset
- Separate admin panel login
- Auto logout on app close
- Attendance day start / end
- Attendance check in / check out
- First-shift close and second/night-shift tracking on the same day
- Break start / end
- Admin attendance sheet with shift summaries and event timeline
- Admin-to-employee announcements
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
- Synced local entries older than the 5-day window are removed from the local view/database.
- Unsynced old entries are kept locally to avoid losing sales if Excel sync failed.
- Excel remains the main permanent sales record.

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

For now, announcements are saved locally in SQLite. When Supabase is connected later, this same feature can sync between your PC and the employee PC.

## Owner App / Employee App Direction

Do not split this into two unrelated projects. Keep one codebase and one shared data design, then package different access modes later:

- Employee mode: employee login, attendance, breaks, sold item entry.
- Admin mode: owner login, attendance sheet, shift timeline, future reports.

For two different PCs to stay linked, the next step will be one shared sync layer, such as a small cloud database/API, a private local-network server, or a controlled shared workbook location. The current SQLite layer gives the app a professional local data foundation, but SQLite by itself is not a live multi-PC sync system.

## Supabase Attendance Sync Later

We will connect Supabase later only for attendance. Sales can stay local/Excel until you are ready.

When it is time, the process will be:

1. Create a free account at `supabase.com`.
2. Create one project for this business app.
3. Create attendance tables for shifts and events.
4. Enable secure rules so the employee app can write attendance but cannot read owner-only reports.
5. Add the Supabase Project URL and anon public key to the app config.
6. Keep local SQLite as an offline cache/backup.

Do not put the Supabase `service_role` key inside the desktop app or packaged `.exe`.

## Future EXE Packaging Notes

The project is ready to package later with a tool such as PyInstaller. The app now separates bundled assets from writable data:

- `assets/` is read-only app content and should be bundled into the `.exe`.
- `data/` is used only while running from source and is ignored by Git.
- In a packaged Windows `.exe`, login/reset data will be stored in the employee user's local app data folder instead of beside the installed program.

Example PyInstaller shape for later:

```powershell
pyinstaller --noconsole --name "Digital Service Pakistan Employee" --icon "assets/app_icon.ico" --add-data "assets;assets" main.py
```
