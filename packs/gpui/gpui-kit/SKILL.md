---
name: gpui-kit
description: >-
  Verified architectural patterns, widget APIs, focus/action dispatch, and Cargo
  checks for building Rust desktop applications with gpui-kit (0.9.1) and GPUI.
  Use when building or updating gpui-kit desktop UIs, views, resizable split panes,
  controlled inputs, Markdown previews, or gpui-kit tutorial lessons.
---

# GPUI Kit (`0.9.1`) Reference Patterns

Use these verified API patterns when building or teaching `gpui-kit` desktop applications. All signatures below are verified against `gpui-kit = "0.9.1"` (`cargo clippy --all-targets -- -D warnings` clean).

## 1. Window Bootstrapping & Notifications (`Root` Included)

`gpui_kit::open_window` automatically wraps your root view inside `gpui_kit::component::Root`. Do **not** manually construct an outer `Root` wrapper unless you need custom modal/sheet hosting beyond standard window setup.

```rust
use gpui_kit::component::WindowExt as _;
use gpui_kit::component::notification::Notification;
use gpui_kit::*;

// Inside main():
gpui_kit::application()
    .with_assets(gpui_kit::assets::Assets)
    .run(|cx| {
        gpui_kit::init(cx);
        register_workbench_keys(cx);
        gpui_kit::open_window(WindowOptions::default(), cx, |window, cx| {
            cx.new(|cx| WorkbenchView::new_with_window(window, cx))
        })
        .expect("failed to open window");
    });

// Anywhere with (&mut Window, &mut Context<Self>):
window.push_notification(Notification::info("Saved session"), cx);
window.push_notification(Notification::error(format!("Save failed: {err}")), cx);
```

- Keep a window-free `pub fn new() -> Self` alongside `pub fn new_with_window(window: &mut Window, cx: &mut Context<Self>) -> Self` with `Option<Entity<...>>` / `Option<FocusHandle>` fields so `cargo test` can instantiate views and exercise pure state logic headlessly.

## 2. Controlled Text Inputs & Code Editors

- Single-line filter/title fields use `Input::new(&entity)` + `Entity<InputState>`.
- Multi-line plain editing uses `Textarea::new(&entity)` + `TextareaState` (`InputState::multi_line`).
- Syntax-highlighted code/Markdown editing uses `Editor::new(&entity)` + `EditorState::new(window, cx)`:

```rust
let editor = cx.new(|cx| {
    EditorState::new(window, cx)
        .language("markdown")
        .line_number(true)
        .soft_wrap(true)
        .default_value(initial_markdown)
});

// Runtime option toggles:
editor.update(cx, |state, cx| {
    state.set_line_number(line_numbers, window, cx);
    state.set_soft_wrap(soft_wrap, window, cx);
});
```

- Store returned `cx.subscribe_in(...)` handles in `_subscriptions: Vec<Subscription>` so RAII keeps listeners alive for the lifetime of the view.
- Programmatic `state.set_value(text, window, cx)` **does not** emit `InputEvent::Change`, allowing clean two-way synchronization between your model and widgets without feedback loops.

## 3. Live Markdown Preview & `WeakEntity` Callbacks

`TextView::markdown(id, source).selectable(true).on_task_toggle(...)` requires a `Send + Sync + 'static` closure. Capture `let view = cx.entity().downgrade();` (`WeakEntity<Self>`) instead of `cx.listener(...)`:

```rust
let view = cx.entity().downgrade();
TextView::markdown("turn-markdown-preview", active_markdown)
    .selectable(true)
    .on_task_toggle(move |event: &TaskToggleEvent, window, cx| {
        let marker_range = event.marker_range();
        let checked = event.checked();
        let _ = view.update(cx, |this, cx| {
            if this.toggle_active_task_marker(marker_range, checked, window, cx) {
                cx.notify();
            }
        });
    })
```

- Always patch source Markdown with `markdown.get(marker_range.clone())?` rather than unchecked indexing so stale byte offsets safely return `None`.

## 4. Resizable Split Panes & Segmented Tabs

```rust
h_resizable("workbench-main-split")
    .child(
        resizable_panel()
            .size(px(320.))
            .size_range(px(220.)..px(520.))
            .child(turn_list_pane),
    )
    .child(resizable_panel().child(right_workspace))
```

- `ResizablePanel` exposes `.size(Pixels)` and `.size_range(Range<Pixels>)` (there is **no** `.min_size(...)`).
- Never call `.flex_basis(...)`, `.absolute()`, or `.overflow_hidden()` directly on `resizable_panel()`—place sizing/scrolling helpers on an inner container `div()` instead.
- Use `.into_any_element()` across conditional `match` layout arms (`EditOnly` vs `Split` nested `h_resizable` vs `PreviewOnly`) so every branch evaluates to `AnyElement`.
- `TabBar::new(...).segmented().selected_index(idx).on_click(...)` passes `&usize` as the click event payload.

## 5. Typed Actions & Keyboard Dispatch

```rust
gpui_kit::actions!(workbench, [SaveSession, ReloadSession]);

pub fn register_workbench_keys(cx: &mut App) {
    cx.bind_keys([
        KeyBinding::new("cmd-s", SaveSession, Some("Workbench")),
        KeyBinding::new("cmd-r", ReloadSession, Some("Workbench")),
    ]);
}
```

Attach `.id(...)`, `.key_context("Workbench")`, `.track_focus(handle)`, and `.on_action(cx.listener(...))` to the outer wrapper `div()` so unhandled key chords bubble up from focused child inputs.
