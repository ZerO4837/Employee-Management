# Version 2.0.9

## New

- **Search in Renewal Services.** Find any account or client in the service you have open by email or phone number, typed in any format (`2460674`, `0334-2460674`, `+92 334 2460674`). Click a result to jump straight to that account and client.
- **Unsaved entry warning.** If an employee starts a sold-item entry or edits an existing one, then switches screen or closes the window without saving, the app asks before discarding it.

## Fixed

- **Attendance timelines missing events.** When a PC was offline for a while, some check-ins and breaks never reached the other PC. Sync now uses the cloud's own clock, and **the missing events are recovered automatically** on the first sync after updating.
- **Other apps opening behind this one.** The app no longer keeps hidden always-on-top windows, so Chrome and other apps come to the front normally.
- **Employee search** now searches the selected day only, and tells you how many matches are on other dates.

## Before updating

1. Run `supabase_delta_cursor.sql` once in the Supabase SQL editor.
2. Update **both PCs** to 2.0.9.

The first sync after updating downloads everything once (about 4 MB in total); after that, cloud usage is the same as before.
