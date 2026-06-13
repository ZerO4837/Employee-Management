# Digital Service Pakistan Employee App

Python desktop app prototype for employee attendance, break tracking, sold item entry, and today-only record review.

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
- Sold item entry form
- Local saved sales entries so accidental close does not wipe today's work
- Today-only entries table
- Edit and remove today's entries

The Excel writing layer is intentionally not connected yet. The next step is to map your real Excel columns and wire entries into the workbook without exposing the full sheet to the employee.

## Project Structure

```text
main.py                 App launcher
app/config.py           Business settings, paths, colors, and form field definitions
app/auth.py             Login and password reset storage
app/storage.py          SQLite attendance shift and event storage
app/utils.py            Date, money, and duration formatting helpers
app/main_app.py         Main Tkinter window and page routing
app/ui/widgets.py       Shared high-fi widgets, gradient elements, cards, buttons
app/ui/login.py         Login screen
app/ui/reset_password.py Password reset screen
app/ui/dashboard.py     Dashboard, attendance, sold item, and today-data screens
app/ui/admin.py         Owner/admin attendance panel
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
- Today's sold item entries
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
