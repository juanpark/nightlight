# UI notes for redesigns

- **Keep `data-tour` attributes when moving or restyling elements.** The first-run tour (`web/lib/tour.ts`,
  `web/components/Tour.tsx`) points at elements by `data-tour="…"` only: `needs`, `map`, `try-own`, `add-device`,
  `found-nearby`, `chat`, `card`, `more` (the header's More menu, where Trust and Settings live). A missing anchor doesn't break the tour (that step shows in
  the middle of the screen), but the pointer is lost. Put the attribute on the element a newcomer should look at.
- New steps go in the `TOURS` list in `web/lib/tour.ts`: `{ id, anchor, title, text, when? }`.
