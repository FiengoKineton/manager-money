# UI + PDF bill scanner patch notes

This patch keeps the existing app flow and storage model, but adds UI refinements and a local PDF-to-expense preview page.

## UI changes

- Add Transaction pages now keep the final `Save expense/income/investment` button floating at the bottom-right of the viewport.
- The grouped account scope switcher no longer opens the active group by default.
- Opening one scope dropdown closes the other scope dropdowns.
- The scope switcher receives phone-specific sticky/menu positioning so the dropdown remains usable on narrow screens.
- Night mode is calmer: darker slate surfaces, lower-saturation accents, weaker decorative glow layers, and less bright cyan/green gradients.
- The topbar now has a `Main Account` shortcut next to the net balance pill.
- The sidebar footer now exposes `Bill scanner` instead of duplicating the profile link, since the profile is already reachable from the user/profile card at the top.

## Bill scanner

New page:

```text
/receipt-scanner
```

Endpoint:

```text
transactions.receipt_scanner
```

The scanner:

1. Accepts one or more PDF/text uploads.
2. Extracts selectable PDF text locally with `pypdf`.
3. Detects merchant, date, total, discounts, and item-like rows using conservative heuristics.
4. Shows editable expense candidates.
5. Asks the user to confirm the selected rows are expenses.
6. Saves selected candidates through the existing `save_new_transaction()` flow.
7. Saves detected item details through the existing receipt storage flow, attached to the saved transaction UID.

Image-only/scanned PDFs are not OCR'd by this patch. They will show an error asking for OCR/selectable text first.

## Added dependency

```text
pypdf>=4.0
```
