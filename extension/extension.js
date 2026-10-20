import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Shell from 'gi://Shell';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as MessageTray from 'resource:///org/gnome/shell/ui/messageTray.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {PHASES, Timer, formatTime} from './timer.js';

const APP_ID = 'dev.joran.Pomodoro.desktop';

// Adwaita palette, light shades so they read well on the dark top bar
const PHASE_COLORS = {
    'work': [0xf6, 0x61, 0x51],
    'short-break': [0x57, 0xe3, 0x89],
    'long-break': [0x62, 0xa0, 0xea],
};

const NOTIFY_TEXT = {
    'work': ['Focus session complete', 'Time for a break.'],
    'short-break': ['Break is over', 'Ready to focus again?'],
    'long-break': ['Long break is over', 'Ready to start a new cycle?'],
};

const PomodoroIndicator = GObject.registerClass(
class PomodoroIndicator extends PanelMenu.Button {
    _init(extension) {
        super._init(0.5, 'Pomodoro');

        this._extension = extension;
        this._settings = extension.getSettings();
        this._timer = new Timer(this._settings);

        const box = new St.BoxLayout({style_class: 'panel-status-menu-box pomodoro-panel-box'});
        this._ring = new St.DrawingArea({
            style_class: 'pomodoro-panel-ring',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._ring.connect('repaint', area => this._drawRing(area));
        this._panelLabel = new St.Label({
            style_class: 'pomodoro-panel-label',
            y_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(this._ring);
        box.add_child(this._panelLabel);
        this.add_child(box);

        this._buildMenu();

        this._settings.connectObject('changed', () => this._queueSync(), this);
        this.menu.connectObject('open-state-changed', () => this._sync(), this);
        Main.sessionMode.connectObject('updated', () => this._syncSessionMode(), this);
        this.connect('destroy', () => this._onDestroy());
        this._syncSessionMode();
        this._sync();
    }

    _buildMenu() {
        this.menu.box.add_style_class_name('pomodoro-menu');

        // Status header: phase, big countdown and transport controls
        const header = new PopupMenu.PopupBaseMenuItem({
            reactive: false,
            can_focus: false,
            style_class: 'pomodoro-header',
        });
        header.setOrnament(PopupMenu.Ornament.HIDDEN);

        const vbox = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL,
            x_expand: true,
        });
        header.add_child(vbox);

        const titleRow = new St.BoxLayout({x_expand: true});
        this._phaseLabel = new St.Label({
            style_class: 'pomodoro-phase-label',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._dots = new St.BoxLayout({
            style_class: 'pomodoro-dots',
            y_align: Clutter.ActorAlign.CENTER,
        });
        titleRow.add_child(this._phaseLabel);
        titleRow.add_child(this._dots);
        vbox.add_child(titleRow);

        this._timeLabel = new St.Label({
            style_class: 'pomodoro-time-label',
            x_align: Clutter.ActorAlign.CENTER,
        });
        vbox.add_child(this._timeLabel);

        this._statusLabel = new St.Label({
            style_class: 'pomodoro-status-label',
            x_align: Clutter.ActorAlign.CENTER,
            opacity: 153,
        });
        vbox.add_child(this._statusLabel);

        const controls = new St.BoxLayout({
            style_class: 'pomodoro-controls',
            x_align: Clutter.ActorAlign.CENTER,
        });
        this._resetButton = this._makeButton('media-playback-stop-symbolic', 'Stop',
            () => this._timer.reset());
        this._playButton = this._makeButton('media-playback-start-symbolic', 'Start',
            () => this._timer.toggle(), 'pomodoro-play-button');
        this._skipButton = this._makeButton('media-skip-forward-symbolic', 'Skip',
            () => this._timer.skip());
        controls.add_child(this._resetButton);
        controls.add_child(this._playButton);
        controls.add_child(this._skipButton);
        vbox.add_child(controls);

        this.menu.addMenuItem(header);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // One item per phase to jump straight into it
        this._phaseItems = {};
        for (const [phase, {title}] of Object.entries(PHASES)) {
            const item = new PopupMenu.PopupMenuItem(title);
            const duration = new St.Label({
                style_class: 'pomodoro-duration-label',
                x_expand: true,
                x_align: Clutter.ActorAlign.END,
                opacity: 153,
            });
            item.add_child(duration);
            item.connect('activate', () => this._timer.start(phase));
            this._phaseItems[phase] = {item, duration};
            this.menu.addMenuItem(item);
        }

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this.menu.addAction('Pomodoro Settings', () => this._openApp());
    }

    _makeButton(iconName, accessibleName, callback, extraClass = '') {
        const button = new St.Button({
            style_class: `icon-button pomodoro-button ${extraClass}`,
            can_focus: true,
            accessible_name: accessibleName,
            child: new St.Icon({icon_name: iconName}),
        });
        button.connect('clicked', callback);
        return button;
    }

    _openApp() {
        const app = Shell.AppSystem.get_default().lookup_app(APP_ID);
        if (app) {
            app.activate();
        } else {
            try {
                Gio.Subprocess.new(['pomodoro'], Gio.SubprocessFlags.NONE);
            } catch (e) {
                logError(e, 'Pomodoro: could not launch app');
            }
        }
        Main.overview.hide();
    }

    _syncSessionMode() {
        // Keep counting (and ringing) on the lock screen, but stay out of its panel
        this.visible = !Main.sessionMode.isLocked;
        if (Main.sessionMode.isLocked)
            this.menu.close();
    }

    vfunc_event(event) {
        // Middle click toggles the timer without opening the menu
        if (event.type() === Clutter.EventType.BUTTON_PRESS &&
            event.get_button() === Clutter.BUTTON_MIDDLE) {
            this._timer.toggle();
            return Clutter.EVENT_STOP;
        }
        return super.vfunc_event(event);
    }

    _queueSync() {
        if (this._syncId)
            return;
        this._syncId = GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            this._syncId = 0;
            this._sync();
            return GLib.SOURCE_REMOVE;
        });
    }

    _sync() {
        const timer = this._timer;

        if (timer.isDue) {
            this._finishPhase();
            return;
        }

        const {phase, state} = timer;
        const remaining = timer.remaining();
        const time = formatTime(remaining);

        // Panel
        this._panelLabel.text = time;
        this._panelLabel.visible =
            state !== 'stopped' && this._settings.get_boolean('show-time-in-panel');
        this._panelLabel.opacity = state === 'paused' ? 153 : 255;
        this._ring.queue_repaint();

        // Menu
        if (this.menu.isOpen) {
            this._phaseLabel.text = PHASES[phase].title;
            this._timeLabel.text = time;
            this._statusLabel.text = this._statusText();

            this._playButton.child.icon_name = state === 'running'
                ? 'media-playback-pause-symbolic' : 'media-playback-start-symbolic';
            this._playButton.accessible_name = state === 'running' ? 'Pause' : 'Start';
            this._resetButton.reactive = state !== 'stopped';
            this._resetButton.opacity = state !== 'stopped' ? 255 : 100;

            this._syncDots();

            for (const [p, {item, duration}] of Object.entries(this._phaseItems)) {
                item.setOrnament(p === phase ? PopupMenu.Ornament.DOT : PopupMenu.Ornament.NO_DOT);
                duration.text = `${timer.duration(p) / 60} min`;
            }
        }

        this._scheduleTick(state === 'running' ? remaining : null);
    }

    _statusText() {
        const timer = this._timer;
        const today = timer.todayCount;
        const todayText = today === 1 ? '1 session today' : `${today} sessions today`;

        switch (timer.state) {
        case 'running': {
            const end = GLib.DateTime.new_from_unix_local(Math.round(timer.endTime));
            return `Until ${end.format('%R')} · ${todayText}`;
        }
        case 'paused':
            return `Paused · ${todayText}`;
        default:
            return todayText;
        }
    }

    _syncDots() {
        const timer = this._timer;
        const interval = timer.interval;
        // Focus sessions finished toward the next long break
        let filled = timer.completed % interval;
        if (timer.completed > 0 && filled === 0)
            filled = interval;

        if (this._dots.get_n_children() !== interval) {
            this._dots.destroy_all_children();
            for (let i = 0; i < interval; i++)
                this._dots.add_child(new St.Widget({style_class: 'pomodoro-dot'}));
        }
        this._dots.get_children().forEach((dot, i) => {
            dot.remove_style_class_name('filled');
            if (i < filled)
                dot.add_style_class_name('filled');
        });
    }

    _scheduleTick(remaining) {
        if (this._tickId) {
            GLib.source_remove(this._tickId);
            this._tickId = 0;
        }
        if (remaining === null)
            return;

        // Wake up right after the displayed second changes
        const fraction = remaining % 1 || 1;
        const delay = Math.max(20, Math.round(fraction * 1000) + 10);
        this._tickId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, delay, () => {
            this._tickId = 0;
            this._sync();
            return GLib.SOURCE_REMOVE;
        });
    }

    _finishPhase() {
        const {finished, next, autoStart} = this._timer.complete();

        if (this._settings.get_boolean('play-sound')) {
            global.display.get_sound_player().play_from_theme(
                finished === 'work' ? 'complete' : 'alarm-clock-elapsed', 'Pomodoro', null);
        }

        const [title, body] = NOTIFY_TEXT[finished];
        const actions = [];
        if (!autoStart)
            actions.push([`Start ${PHASES[next].title}`, () => this._timer.start(next)]);
        else
            actions.push(['Skip', () => this._timer.skip()]);
        this._notify(title, body, actions);
    }

    _notify(title, body, actions) {
        if (!this._source) {
            this._source = new MessageTray.Source({
                title: 'Pomodoro',
                icon: Gio.icon_new_for_string(
                    `${this._extension.path}/icons/pomodoro-symbolic.svg`),
            });
            this._source.connect('destroy', () => {
                this._source = null;
            });
            Main.messageTray.add(this._source);
        }

        this._notification?.destroy();
        const notification = new MessageTray.Notification({
            source: this._source,
            title,
            body,
            urgency: MessageTray.Urgency.HIGH,
        });
        notification.connect('destroy', () => {
            if (this._notification === notification)
                this._notification = null;
        });
        for (const [label, callback] of actions)
            notification.addAction(label, callback);
        this._notification = notification;
        this._source.addNotification(notification);
    }

    _drawRing(area) {
        const cr = area.get_context();
        const [width, height] = area.get_surface_size();
        const fg = area.get_theme_node().get_foreground_color();
        const timer = this._timer;
        const {phase, state} = timer;

        const cx = width / 2;
        const cy = height / 2;
        const lineWidth = 1.5;
        const radius = Math.min(width, height) / 2 - lineWidth / 2;
        const top = -Math.PI / 2;

        // Outer ring
        cr.setLineWidth(lineWidth);
        cr.setSourceRGBA(fg.red / 255, fg.green / 255, fg.blue / 255,
            state === 'stopped' ? 1 : 0.4);
        cr.arc(cx, cy, radius, 0, 2 * Math.PI);
        cr.stroke();

        // Remaining time as a shrinking pie, like a kitchen timer
        const remaining = state === 'stopped' ? 1 : 1 - timer.progress();
        if (remaining > 0) {
            const [r, g, b] = PHASE_COLORS[phase];
            if (state === 'paused')
                cr.setSourceRGBA(fg.red / 255, fg.green / 255, fg.blue / 255, 0.6);
            else if (state === 'stopped')
                cr.setSourceRGBA(fg.red / 255, fg.green / 255, fg.blue / 255, 1);
            else
                cr.setSourceRGBA(r / 255, g / 255, b / 255, 1);

            const pieRadius = state === 'stopped' ? radius * 0.3 : radius - lineWidth - 0.5;
            cr.moveTo(cx, cy);
            if (state === 'stopped')
                cr.arc(cx, cy, pieRadius, 0, 2 * Math.PI);
            else
                cr.arc(cx, cy, pieRadius, top, top + remaining * 2 * Math.PI);
            cr.closePath();
            cr.fill();
        }

        cr.$dispose();
    }

    _onDestroy() {
        if (this._syncId)
            GLib.source_remove(this._syncId);
        if (this._tickId)
            GLib.source_remove(this._tickId);
        this._syncId = this._tickId = 0;
    }

    destroyNotifications() {
        this._source?.destroy();
        this._source = null;
    }
});

export default class PomodoroExtension extends Extension {
    enable() {
        this._indicator = new PomodoroIndicator(this);
        Main.panel.addToStatusArea(this.uuid, this._indicator, 0, 'right');
    }

    disable() {
        this._indicator?.destroyNotifications();
        this._indicator?.destroy();
        this._indicator = null;
    }
}
