# Visual design contract v2

New plans freeze version 2.0.0 with the chosen style, distinct execution signatures and rules. Every shot has an editable `design`: style, composition/occupancy, camera, depth/evidence layers, lighting, typography/reading path, and rationale/variation. Fixed presets cannot silently switch style. Auto must choose a concrete style per shot. Product identity, evidence, user requirements and loaded skills remain authoritative; Listing mains remain product-only without added copy or graphic decoration.

The brief response schema requires the design object for v2. Missing or invalid designs can be corrected within the same agent conversation with at most two continuations, retaining the draft and skill context. Save/confirmation validates presence, field limits and preset consistency. Repeated layout/design text produces visible reminders; this is not semantic comparison or visual approval.

While saving the prompt draft, the server binds the confirmed design and frozen campaign rules into a visible `[Approved visual design v2]` block. Binding is idempotent, and reference choices still come from the confirmed brief. Generation submits the confirmed prompt without rewriting it. Vision review receives the same per-shot design and is asked to report actual deviations or uncertainty. No automatic paid redraw is added for style deviations.

Existing frozen plans retain their old version until the user explicitly adopts the new rules or changes their style. Upgrade clears active brief/prompts for reconfirmation while retaining analysis, history and images. Cases and shared copies preserve their frozen version. Mobile A+ adapts the new design contract to 4:3 rather than reusing desktop text coordinates.

Validation: backend design/snapshot/prompt/review/mobile tests, bounded agent continuation tests; frontend typecheck and existing unit tests; mocked browser tests for design editing, explicit upgrade, account flow and 390px layout. No paid image calls are used by these tests.
