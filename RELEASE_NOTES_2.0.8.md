# Version 2.0.8

## New

- **Inventory now handles two kinds of service.** Timed ones (Proton VPN) count down from the purchase date — 30 days by default, turning red in the last 5. Shared ones (Canva, Spotify, Adobe) track slots instead.
- **Use Slot.** The employee records the client email and package, and the free-slot count drops by one. Employees can correct a client's email later; removing a client is admin-only and frees the slot on both PCs.
- **Renewal accounts are sold in their own right** — each has its own package, expiry, days left and client number. **Close** returns an account to In Stock when a client doesn't renew, and **Renew** adds time on top of what's left.
- **Type-ahead on date dropdowns** — type `11` for the 11th, `aug` for August.

## Improved

- Admin sales window is now **Last 30 Days**, and searching keeps whatever date or month you picked instead of silently widening it.
- The employee's ten date boxes are now one compact row, giving the entries table about 170px more room.
- Employee Inventory list widened so service names and emails are no longer cut off.

## Fixed

- The mouse wheel no longer changes dropdown values while you scroll a page.
- The mouse wheel over a list scrolls that list, not the whole page.
- Expired renewal accounts no longer show a green expiry date left over from another account.
- Renewal passwords no longer run into the Client Number column.

## Before updating

Both PCs need 2.0.8 for inventory slot sharing. Cloud usage is unchanged.
