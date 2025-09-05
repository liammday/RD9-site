# Rules to Tame iOS Safari Layout Weirdness (Tailwind-ready)

1. **Stop using `h-screen` for full-height UI; switch to the new viewport units**
   - Prefer `dvh`/`svh`/`lvh` instead of `vh`. In Tailwind 3.4+ you get them as classes: `h-dvh`, `h-svh`, `h-lvh`.
   - Use dynamic height (`dvh`) for things that must follow the toolbar expanding/collapsing (drawers, full-screen modals).
   - Use small height (`svh`) when you want to avoid jumpiness while the bars are visible (initial loads).
   - Use large height (`lvh`) for “max possible” layouts (e.g., splash screens), but expect overshoot if the bars are visible.

   **Example (Tailwind):**
   ```html
   <!-- App shell that adapts as Safari UI expands/collapses -->
   <div class="min-h-dvh flex flex-col">
     <header class="sticky top-0 z-50">…</header>
     <main class="grow overflow-auto">…</main>
   </div>
   ```
   *Why:* `vh` maps to the large viewport (roughly `lvh`), which often overflows under the bottom bar; `dvh`/`svh`/`lvh` were added to fix this exact problem.

2. **Always include safe-area handling (the notch & bottom bar)**
   - Add `viewport-fit=cover` in your `<meta name="viewport">`.
   - Pad fixed or full-bleed elements using the `env(safe-area-inset-*)` variables.

   **Tailwind utility (one-off CSS):**
   ```css
   /* globals.css */
   :root {
     --safe-top: env(safe-area-inset-top);
     --safe-bottom: env(safe-area-inset-bottom);
   }
   ```
   ```html
   <!-- Fixed header/footer that won’t clash with the notch/bars -->
   <header class="fixed inset-x-0 top-0 pt-[var(--safe-top)]">…</header>
   <footer class="fixed inset-x-0 bottom-0 pb-[var(--safe-bottom)]">…</footer>
   ```
   *Why:* `env(safe-area-inset-*)` ensures fixed chrome doesn’t sit under the notch or toolbar. Works only when `viewport-fit=cover` is set.

3. **Prefer sticky over fixed for navbars where possible**
   - Safari still exhibits odd reflow when address bars collapse/expand with `position: fixed`.
   - A sticky header on a scrolling container is more stable and avoids viewport recalculations.

   **Example (Tailwind):**
   ```html
   <div class="min-h-dvh flex flex-col">
     <header class="sticky top-0 z-50">…</header>
     <main class="grow overflow-auto overscroll-contain">…</main>
   </div>
   ```
   *Why:* fixed elements can shift when Safari’s chrome changes size; sticky ties the element to the scrolling context instead.

4. **If you must use fixed, pin via insets — not `height: 100vh`**

   Use `inset-0` + safe-area padding and let the element fill using positioned edges rather than relying on viewport units.

   **Modal overlay (Tailwind):**
   ```html
   <div id="overlay" class="fixed inset-0 pt-[var(--safe-top)] pb-[var(--safe-bottom)] z-50">
     <div class="h-full overflow-auto overscroll-contain">…</div>
   </div>
   ```
   *Why:* `inset-0` with safe-area padding survives toolbar transitions better than `h-screen`.

5. **Lock background scroll the modern way (no janky JS)**
   - When opening a modal/drawer:
     1. Add `overflow-hidden` to `html` and `body`, and set their height to `100dvh`.
     2. Prevent scroll chaining with `overscroll-behavior: none` on the scrolling overlay.

   **Global helper classes:**
   ```css
   /* globals.css */
   html.modal-open, body.modal-open { height: 100dvh; overflow: hidden; }
   .modal-scrollbox { overscroll-behavior: none; -webkit-overflow-scrolling: touch; }
   ```
   ```html
   <div class="fixed inset-0 z-50">
     <div class="modal-scrollbox h-dvh overflow-auto">…</div>
   </div>
   <script>
     // when opening the modal
     document.documentElement.classList.add('modal-open');
     document.body.classList.add('modal-open');
     // remove both on close
   </script>
   ```
   *Why:* prevents the classic “page scrolls behind modal” on iOS; `overscroll-behavior` stops scroll chaining; `100dvh` keeps the lock stable as UI chrome moves.

6. **Make scrollable regions explicit**
   - Any scrollable area inside a fixed/sticky container should have:
     `overflow-auto`, `overscroll-contain` (or `overscroll-behavior: contain`), and momentum scrolling: `-webkit-overflow-scrolling: touch`.

   **Example:**
   ```html
   <div class="fixed inset-0">
     <div class="h-full overflow-auto overscroll-contain [@supports(-webkit-overflow-scrolling:touch)]:[-webkit-overflow-scrolling:touch]">
       …
     </div>
   </div>
   ```
   *Why:* this prevents the “bounce to body” and preserves smooth scrolling on iOS.

7. **Keyboard-safe forms**
   - Avoid `100vh` near inputs; favour `min-h-svh` or natural flow so the on-screen keyboard doesn’t shove fixed elements off.
   - Keep actionable buttons in a non-fixed container that can move with content when the keyboard opens.

   *Why:* iOS can temporarily ignore fixed while the keyboard is open or shift the visual viewport unpredictably.

8. **Progressive fallbacks for older/buggy engines**
   - Some WebKit builds historically didn’t distinguish `svh` and `dvh`. Provide layered fallbacks:

   **Fallback stack (CSS):**
   ```css
   .full-height {
     height: 100vh;        /* legacy fallback */
     height: 100svh;       /* when bars are visible */
     height: 100dvh;       /* modern dynamic */
   }
   ```
   In Tailwind you can mirror this with a utility class in your CSS layer or apply multiple classes via `@apply`.

9. **Tailwind “starter kit” for iOS-safe layouts**

   Add these once and reuse:
   ```css
   /* globals.css */
   /* 1) Safe areas */
   :root{
     --safe-top: env(safe-area-inset-top);
     --safe-right: env(safe-area-inset-right);
     --safe-bottom: env(safe-area-inset-bottom);
     --safe-left: env(safe-area-inset-left);
   }

   /* 2) Modal scroll lock */
   html.modal-open, body.modal-open { height: 100dvh; overflow: hidden; }

   /* 3) Helpers */
   .ios-safe-padding   { padding-top: var(--safe-top); padding-bottom: var(--safe-bottom); }
   .ios-safe-inset     { inset: 0; padding-top: var(--safe-top); padding-bottom: var(--safe-bottom); }
   .ios-scrollbox      { overflow: auto; overscroll-behavior: none; -webkit-overflow-scrolling: touch; }
   ```

   **HTML head:**
   ```html
   <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
   ```

10. **When things still look cursed**
    - Replace fixed with `absolute` + `inset-0` and drive visibility with transforms/opacities.
    - Recalculate heights on orientation change and when a PWA is launched in standalone mode (applies fewer now, but still relevant if you see mismatches).

---

### Key sources (recent & authoritative)
- Dynamic viewport units (svh/lvh/dvh), why they exist and how to use them (WebKit blog + web.dev + caniuse).
- Known Safari mismatches with svh/dvh in certain builds; provide fallbacks.
- Safe-area environment variables and `viewport-fit=cover` (MDN, CSS-Tricks).
- Tailwind support for dvh/svh/lvh units.
- Fixed/sticky displacement and keyboard quirks on iOS.
- Scroll-locking patterns (`overscroll-behavior`, CSS-first approaches).
