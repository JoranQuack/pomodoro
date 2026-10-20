#!/usr/bin/python3
"""Pomodoro: a libadwaita front end for the Pomodoro top bar extension.

Timer state lives in GSettings (schema shipped with the extension), so this
window and the top bar indicator always show the same timer. The extension is
the engine that finishes phases and notifies; when it isn't running, the app
takes over that job while its window is open.
"""

import math
import os
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

APP_ID = "dev.joran.Pomodoro"
EXTENSION_UUID = "pomodoro@joran.dev"
SCHEMA_ID = "org.gnome.shell.extensions.pomodoro"

PHASES = {
    "work": ("Focus", "work-duration", Adw.AccentColor.RED),
    "short-break": ("Short Break", "short-break-duration", Adw.AccentColor.GREEN),
    "long-break": ("Long Break", "long-break-duration", Adw.AccentColor.BLUE),
}

NOTIFY_TEXT = {
    "work": ("Focus session complete", "Time for a break."),
    "short-break": ("Break is over", "Ready to focus again?"),
    "long-break": ("Long break is over", "Ready to start a new cycle?"),
}


def load_settings():
    dirs = [
        os.path.join(GLib.get_user_data_dir(), "gnome-shell", "extensions", EXTENSION_UUID, "schemas"),
        os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "extension", "schemas"),
    ]
    default = Gio.SettingsSchemaSource.get_default()
    for d in dirs:
        if os.path.exists(os.path.join(d, "gschemas.compiled")):
            source = Gio.SettingsSchemaSource.new_from_directory(d, default, False)
            schema = source.lookup(SCHEMA_ID, False)
            if schema:
                return Gio.Settings.new_full(schema, None, None)
    return Gio.Settings.new(SCHEMA_ID)


def today():
    return GLib.DateTime.new_now_local().format("%F")


def format_time(seconds):
    seconds = math.ceil(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"


class Timer:
    """Python port of extension/timer.js; keep the two in sync."""

    def __init__(self, settings):
        self.s = settings

    @property
    def phase(self):
        return self.s.get_string("phase")

    @property
    def state(self):
        return self.s.get_string("state")

    @property
    def interval(self):
        return self.s.get_int("long-break-interval")

    @property
    def completed(self):
        return self.s.get_int("completed")

    @property
    def end_time(self):
        return self.s.get_double("end-time")

    @property
    def today_count(self):
        if self.s.get_string("today-date") != today():
            return 0
        return self.s.get_int("today-count")

    def duration(self, phase=None):
        return self.s.get_int(PHASES[phase or self.phase][1]) * 60

    def remaining(self):
        state = self.state
        if state == "running":
            return max(0.0, self.end_time - time.time())
        if state == "paused":
            return self.s.get_double("remaining")
        return float(self.duration())

    def progress(self):
        duration = self.duration()
        if duration <= 0:
            return 0.0
        return min(1.0, max(0.0, 1 - self.remaining() / duration))

    @property
    def is_due(self):
        return self.state == "running" and self.end_time - time.time() <= 0

    def _write(self, func):
        self.s.delay()
        func(self.s)
        self.s.apply()

    def _next_phase(self, completed):
        if self.phase != "work":
            return "work"
        return "long-break" if completed > 0 and completed % self.interval == 0 else "short-break"

    def start(self, phase=None):
        phase = phase or self.phase

        def write(s):
            s.set_string("phase", phase)
            s.set_string("state", "running")
            s.set_double("end-time", time.time() + self.duration(phase))

        self._write(write)

    def pause(self):
        if self.state != "running":
            return
        remaining = self.remaining()

        def write(s):
            s.set_string("state", "paused")
            s.set_double("remaining", remaining)

        self._write(write)

    def resume(self):
        if self.state != "paused":
            return
        remaining = self.s.get_double("remaining")

        def write(s):
            s.set_string("state", "running")
            s.set_double("end-time", time.time() + remaining)

        self._write(write)

    def toggle(self):
        {"running": self.pause, "paused": self.resume}.get(self.state, self.start)()

    def reset(self):
        self._write(lambda s: s.set_string("state", "stopped"))

    def select(self, phase):
        def write(s):
            s.set_string("phase", phase)
            s.set_string("state", "stopped")

        self._write(write)

    def skip(self):
        next_phase = self._next_phase(self.completed + 1)
        if self.state == "stopped":
            self.select(next_phase)
            return
        if self.phase == "long-break":
            self.s.set_int("completed", 0)
        self.start(next_phase)

    def complete(self):
        finished = self.phase
        completed = self.completed
        if finished == "work":
            completed += 1
        next_phase = self._next_phase(completed)
        if finished == "long-break":
            completed = 0
        auto_start = self.s.get_boolean("auto-start-work" if next_phase == "work" else "auto-start-breaks")
        today_count = self.today_count

        def write(s):
            s.set_int("completed", completed)
            if finished == "work":
                s.set_int("today-count", today_count + 1)
                s.set_string("today-date", today())
            s.set_string("phase", next_phase)
            s.set_string("state", "running" if auto_start else "stopped")
            s.set_double("end-time", time.time() + self.duration(next_phase))

        self._write(write)
        return finished, next_phase, auto_start


class TimerDial(Gtk.Overlay):
    """Circular progress ring, drawn like a GNOME Clocks timer."""

    def __init__(self, timer):
        super().__init__(css_classes=["timer-dial"])
        self.timer = timer

        self.area = Gtk.DrawingArea(content_width=260, content_height=260)
        self.area.set_draw_func(self._draw)
        self.set_child(self.area)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        self.time_label = Gtk.Label(css_classes=["timer-label", "numeric"])
        self.status_label = Gtk.Label(css_classes=["dim-label", "timer-status"])
        box.append(self.time_label)
        box.append(self.status_label)
        self.add_overlay(box)

    def _draw(self, area, cr, width, height):
        timer = self.timer
        style = Adw.StyleManager.get_default()
        dark = style.get_dark()
        fg = area.get_color()

        size = min(width, height)
        line = 10
        radius = size / 2 - line / 2
        cx, cy = width / 2, height / 2
        top = -math.pi / 2

        cr.set_line_width(line)
        cr.set_line_cap(1)  # round
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.1)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()

        progress = timer.progress()
        if timer.state == "stopped" or progress <= 0:
            return

        color = Adw.AccentColor.to_standalone_rgba(PHASES[timer.phase][2], dark)
        alpha = 0.45 if timer.state == "paused" else 1.0
        cr.set_source_rgba(color.red, color.green, color.blue, alpha)
        cr.arc(cx, cy, radius, top, top + progress * 2 * math.pi)
        cr.stroke()


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, settings):
        super().__init__(title="Preferences", search_enabled=False)
        self.settings = settings
        page = Adw.PreferencesPage()
        self.add(page)

        durations = Adw.PreferencesGroup(title="Durations")
        durations.add(self._spin("work-duration", "Focus", "Minutes", 1, 180))
        durations.add(self._spin("short-break-duration", "Short Break", "Minutes", 1, 60))
        durations.add(self._spin("long-break-duration", "Long Break", "Minutes", 1, 120))
        page.add(durations)

        cycle = Adw.PreferencesGroup(title="Cycle")
        cycle.add(self._spin("long-break-interval", "Long Break Every", "Focus sessions", 2, 12))
        cycle.add(self._switch("auto-start-breaks", "Start Breaks Automatically"))
        cycle.add(self._switch("auto-start-work", "Start Focus Automatically", "Begin the next session as soon as a break ends"))
        page.add(cycle)

        other = Adw.PreferencesGroup(title="Notifications")
        other.add(self._switch("play-sound", "Play Sound", "When a session or break ends"))
        other.add(self._switch("show-time-in-panel", "Show Time in Top Bar"))
        page.add(other)

    def _spin(self, key, title, subtitle, lower, upper):
        row = Adw.SpinRow.new_with_range(lower, upper, 1)
        row.set_title(title)
        row.set_subtitle(subtitle)
        row.set_value(self.settings.get_int(key))
        row.connect("notify::value", lambda r, _: self.settings.set_int(key, int(r.get_value())))
        return row

    def _switch(self, key, title, subtitle=None):
        row = Adw.SwitchRow(title=title, subtitle=subtitle or "")
        self.settings.bind(key, row, "active", Gio.SettingsBindFlags.DEFAULT)
        return row


class PomodoroWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Pomodoro", default_width=400, default_height=620)
        self.set_size_request(320, 480)
        self.app = app
        self.settings = app.settings
        self.timer = app.timer

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        self.phase_group = Adw.ToggleGroup(css_classes=["round"], halign=Gtk.Align.CENTER)
        for phase, (title, _, _) in PHASES.items():
            self.phase_group.add(Adw.Toggle(name=phase, label=title))
        self.phase_group.connect("notify::active-name", self._on_phase_selected)

        menu = Gio.Menu()
        menu.append("_Preferences", "app.preferences")
        menu.append("_Keyboard Shortcuts", "app.shortcuts")
        menu.append("_About Pomodoro", "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       tooltip_text="Main Menu", primary=True))
        toolbar.add_top_bar(header)


        # Content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24, valign=Gtk.Align.CENTER,
                          margin_top=12, margin_bottom=36, margin_start=24, margin_end=24)
        content.append(self.phase_group)

        self.dial = TimerDial(self.timer)
        content.append(self.dial)

        self.dots = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        self.session_label = Gtk.Label(css_classes=["dim-label", "caption"])
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        info.append(self.dots)
        info.append(self.session_label)
        content.append(info)

        controls = Gtk.Box(spacing=18, halign=Gtk.Align.CENTER)
        self.reset_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Reset",
                                       css_classes=["circular", "flat", "control-button"], valign=Gtk.Align.CENTER)
        self.reset_button.connect("clicked", lambda *_: self.timer.reset())
        self.main_button = Gtk.Button(css_classes=["pill", "suggested-action", "main-button"])
        self.main_button.connect("clicked", lambda *_: self.timer.toggle())
        self.skip_button = Gtk.Button(icon_name="media-skip-forward-symbolic", tooltip_text="Skip",
                                      css_classes=["circular", "flat", "control-button"], valign=Gtk.Align.CENTER)
        self.skip_button.connect("clicked", lambda *_: self.timer.skip())
        controls.append(self.reset_button)
        controls.append(self.main_button)
        controls.append(self.skip_button)
        content.append(controls)

        clamp = Adw.Clamp(maximum_size=420, child=content)
        toolbar.set_content(clamp)
        self.set_content(toolbar)

        self._syncing = False
        self._tick_id = 0
        self._sync_id = 0
        self._changed_id = self.settings.connect("changed", lambda *_: self._queue_sync())
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self.dial.area.queue_draw())
        self.connect("close-request", self._on_close)

        self.check_extension()
        self._sync()

    # Extension status -----------------------------------------------------

    def check_extension(self):
        self.extension_state = self.app.extension_state()

    # Sync -------------------------------------------------------------------

    def _queue_sync(self):
        if not self._sync_id:
            self._sync_id = GLib.idle_add(self._idle_sync)

    def _idle_sync(self):
        self._sync_id = 0
        self._sync()
        return False

    def _on_phase_selected(self, group, _pspec):
        if self._syncing:
            return
        phase = group.get_active_name()
        if phase and phase != self.timer.phase:
            self.timer.select(phase)

    def _sync(self):
        timer = self.timer

        # With the top bar extension running, it owns phase transitions
        if timer.is_due and self.extension_state != "active":
            self.app.finish_phase()
            return

        phase, state = timer.phase, timer.state
        remaining = timer.remaining()

        self._syncing = True
        self.phase_group.set_active_name(phase)
        self._syncing = False

        self.dial.time_label.set_label(format_time(remaining))
        if state == "running":
            end = GLib.DateTime.new_from_unix_local(round(timer.end_time))
            self.dial.status_label.set_label(f"Until {end.format('%R')}")
        elif state == "paused":
            self.dial.status_label.set_label("Paused")
        else:
            self.dial.status_label.set_label(PHASES[phase][0])
        self.dial.area.queue_draw()

        for cls in ("work", "short-break", "long-break"):
            self.dial.remove_css_class(cls)
        self.dial.add_css_class(phase)

        self.main_button.set_label({"running": "Pause", "paused": "Resume"}.get(state, "Start"))
        self.reset_button.set_sensitive(state != "stopped")

        self._sync_dots()
        n = timer.today_count
        left = timer.interval - (timer.completed % timer.interval)
        if timer.completed > 0 and left == timer.interval:
            cycle = "Long break earned"
        else:
            cycle = f"{left} until long break"
        self.session_label.set_label(f"{cycle} · {n} today")

        self._schedule_tick(state == "running")

    def _sync_dots(self):
        timer = self.timer
        interval = timer.interval
        # Focus sessions finished toward the next long break; all filled = long break earned
        filled = timer.completed % interval
        if timer.completed > 0 and filled == 0:
            filled = interval

        children = []
        child = self.dots.get_first_child()
        while child:
            children.append(child)
            child = child.get_next_sibling()
        if len(children) != interval:
            for c in children:
                self.dots.remove(c)
            children = [Gtk.Box(css_classes=["session-dot"], valign=Gtk.Align.CENTER) for _ in range(interval)]
            for c in children:
                self.dots.append(c)
        for i, dot in enumerate(children):
            if i < filled:
                dot.add_css_class("filled")
            else:
                dot.remove_css_class("filled")
        self.dots.set_tooltip_text(f"{filled} of {interval} focus sessions before a long break")

    def _schedule_tick(self, running):
        if self._tick_id:
            GLib.source_remove(self._tick_id)
            self._tick_id = 0
        if running:
            # Redraw often enough for a smooth ring
            self._tick_id = GLib.timeout_add(100, self._on_tick)

    def _on_tick(self):
        self._tick_id = 0
        self._sync()
        return False

    def _on_close(self, *_):
        if self._tick_id:
            GLib.source_remove(self._tick_id)
            self._tick_id = 0
        self.settings.disconnect(self._changed_id)
        return False


CSS = """
.timer-label {
  font-size: 48pt;
  font-weight: 300;
}
.timer-status {
  font-weight: bold;
}
.main-button {
  min-width: 120px;
  min-height: 48px;
  font-size: 1.1em;
}
.control-button {
  min-width: 48px;
  min-height: 48px;
}
.session-dot {
  min-width: 10px;
  min-height: 10px;
  border-radius: 99px;
  background-color: alpha(currentColor, 0.15);
}
.session-dot.filled {
  background-color: var(--accent-bg-color);
}
"""


class PomodoroApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        GLib.set_application_name("Pomodoro")
        self.add_main_option("start", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             "Start a phase without opening the window", "work|short-break|long-break")
        self.settings = load_settings()
        self.timer = Timer(self.settings)
        self._shell = None

    def do_startup(self):
        Adw.Application.do_startup(self)

        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        actions = {
            "toggle": (lambda *_: self.timer.toggle(), ["space"]),
            "reset": (lambda *_: self.timer.reset(), ["<Control>r"]),
            "skip": (lambda *_: self.timer.skip(), ["<Control>n"]),
            "preferences": (self._on_preferences, ["<Control>comma"]),
            "shortcuts": (self._on_shortcuts, ["<Control>question"]),
            "about": (self._on_about, []),
            "quit": (lambda *_: self.quit(), ["<Control>q"]),
            "close": (lambda *_: self.get_active_window() and self.get_active_window().close(), ["<Control>w"]),
            "start-phase": (lambda _a, p: self.timer.start(p.get_string()), []),
        }
        for name, (callback, accels) in actions.items():
            param = GLib.VariantType.new("s") if name == "start-phase" else None
            action = Gio.SimpleAction.new(name, param)
            action.connect("activate", callback)
            self.add_action(action)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)

    def do_command_line(self, command_line):
        options = command_line.get_options_dict().end().unpack()
        phase = options.get("start")
        if phase:
            if phase not in PHASES:
                command_line.printerr(f"Unknown phase {phase!r}\n")
                return 1
            self.timer.start(phase)
            return 0
        self.activate()
        return 0

    def do_activate(self):
        win = self.get_active_window() or PomodoroWindow(self)
        win.check_extension()
        win.present()

    # GNOME Shell extension helpers ----------------------------------------

    def _shell_proxy(self):
        if self._shell is None:
            self._shell = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
                "org.gnome.Shell", "/org/gnome/Shell",
                "org.gnome.Shell.Extensions", None)
        return self._shell

    def extension_state(self):
        """'active', 'disabled' or 'missing' (not loaded by the running shell)."""
        try:
            info = self._shell_proxy().call_sync(
                "GetExtensionInfo", GLib.Variant("(s)", (EXTENSION_UUID,)),
                Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        except GLib.Error:
            return "missing"
        if not info:
            return "missing"
        if int(info.get("state", 0)) == 1:
            return "active"
        return "disabled"

    def enable_extension(self):
        try:
            self._shell_proxy().call_sync(
                "EnableExtension", GLib.Variant("(s)", (EXTENSION_UUID,)),
                Gio.DBusCallFlags.NONE, 2000, None)
        except GLib.Error as e:
            print(f"Could not enable extension: {e.message}", file=sys.stderr)

    # Fallback engine, used only while the extension is not running ---------

    def finish_phase(self):
        finished, next_phase, auto_start = self.timer.complete()
        title, body = NOTIFY_TEXT[finished]
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        notification.set_priority(Gio.NotificationPriority.HIGH)
        if not auto_start:
            notification.add_button_with_target(f"Start {PHASES[next_phase][0]}", "app.start-phase",
                                                GLib.Variant("s", next_phase))
        self.send_notification("phase-finished", notification)

    # Dialogs ------------------------------------------------------------------

    def _on_preferences(self, *_):
        PreferencesDialog(self.settings).present(self.get_active_window())

    def _on_shortcuts(self, *_):
        dialog = Adw.ShortcutsDialog()
        section = Adw.ShortcutsSection(title="Timer")
        for title, accel in [("Start / Pause", "space"), ("Reset", "<Control>r"), ("Skip", "<Control>n")]:
            section.add(Adw.ShortcutsItem(title=title, accelerator=accel))
        dialog.add(section)
        general = Adw.ShortcutsSection(title="General")
        for title, accel in [("Preferences", "<Control>comma"), ("Keyboard Shortcuts", "<Control>question"),
                             ("Close Window", "<Control>w"), ("Quit", "<Control>q")]:
            general.add(Adw.ShortcutsItem(title=title, accelerator=accel))
        dialog.add(general)
        dialog.present(self.get_active_window())

    def _on_about(self, *_):
        Adw.AboutDialog(
            application_name="Pomodoro",
            application_icon=APP_ID,
            developer_name="Joran Le Quellec",
            version="1.0",
            comments="Focus in short sessions with breaks in between. The timer lives in the top bar.",
            license_type=Gtk.License.GPL_3_0,
        ).present(self.get_active_window())


if __name__ == "__main__":
    sys.exit(PomodoroApp().run(sys.argv))
