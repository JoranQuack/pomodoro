// Pomodoro timer state machine on top of GSettings.
//
// All state lives in GSettings so the top bar extension and the app share it;
// whoever changes it, the other side picks it up through the 'changed' signal.

import GLib from 'gi://GLib';

export const PHASES = {
    'work': {title: 'Focus', key: 'work-duration'},
    'short-break': {title: 'Short Break', key: 'short-break-duration'},
    'long-break': {title: 'Long Break', key: 'long-break-duration'},
};

function now() {
    return GLib.get_real_time() / 1e6;
}

function today() {
    return GLib.DateTime.new_now_local().format('%F');
}

export class Timer {
    constructor(settings) {
        this._settings = settings;
    }

    get phase() {
        return this._settings.get_string('phase');
    }

    get state() {
        return this._settings.get_string('state');
    }

    get interval() {
        return this._settings.get_int('long-break-interval');
    }

    get completed() {
        return this._settings.get_int('completed');
    }

    get todayCount() {
        if (this._settings.get_string('today-date') !== today())
            return 0;
        return this._settings.get_int('today-count');
    }

    get endTime() {
        return this._settings.get_double('end-time');
    }

    duration(phase = this.phase) {
        return this._settings.get_int(PHASES[phase].key) * 60;
    }

    remaining() {
        switch (this.state) {
        case 'running':
            return Math.max(0, this.endTime - now());
        case 'paused':
            return this._settings.get_double('remaining');
        default:
            return this.duration();
        }
    }

    progress() {
        const duration = this.duration();
        if (duration <= 0)
            return 0;
        return Math.min(1, Math.max(0, 1 - this.remaining() / duration));
    }

    get isDue() {
        return this.state === 'running' && this.endTime - now() <= 0;
    }

    _write(func) {
        this._settings.delay();
        func(this._settings);
        this._settings.apply();
    }

    _nextPhase(completed) {
        if (this.phase !== 'work')
            return 'work';
        return completed > 0 && completed % this.interval === 0
            ? 'long-break' : 'short-break';
    }

    start(phase = this.phase) {
        this._write(s => {
            s.set_string('phase', phase);
            s.set_string('state', 'running');
            s.set_double('end-time', now() + this.duration(phase));
        });
    }

    pause() {
        if (this.state !== 'running')
            return;
        const remaining = this.remaining();
        this._write(s => {
            s.set_string('state', 'paused');
            s.set_double('remaining', remaining);
        });
    }

    resume() {
        if (this.state !== 'paused')
            return;
        const remaining = this._settings.get_double('remaining');
        this._write(s => {
            s.set_string('state', 'running');
            s.set_double('end-time', now() + remaining);
        });
    }

    toggle() {
        switch (this.state) {
        case 'running':
            this.pause();
            break;
        case 'paused':
            this.resume();
            break;
        default:
            this.start();
        }
    }

    reset() {
        this._write(s => s.set_string('state', 'stopped'));
    }

    // Select a phase without starting it
    select(phase) {
        this._write(s => {
            s.set_string('phase', phase);
            s.set_string('state', 'stopped');
        });
    }

    // Move on to the next phase without counting the current one
    skip() {
        const next = this._nextPhase(this.completed + 1);
        if (this.state === 'stopped') {
            this.select(next);
        } else {
            this._write(s => {
                if (this.phase === 'long-break')
                    s.set_int('completed', 0);
            });
            this.start(next);
        }
    }

    // Called when a running phase reaches zero. Returns {finished, next}.
    complete() {
        const finished = this.phase;
        let completed = this.completed;

        if (finished === 'work')
            completed++;
        const next = this._nextPhase(completed);
        if (finished === 'long-break')
            completed = 0;

        const autoStart = next === 'work'
            ? this._settings.get_boolean('auto-start-work')
            : this._settings.get_boolean('auto-start-breaks');

        this._write(s => {
            s.set_int('completed', completed);
            if (finished === 'work') {
                s.set_int('today-count', this.todayCount + 1);
                s.set_string('today-date', today());
            }
            s.set_string('phase', next);
            s.set_string('state', autoStart ? 'running' : 'stopped');
            s.set_double('end-time', now() + this.duration(next));
        });

        return {finished, next, autoStart};
    }
}

export function formatTime(seconds) {
    seconds = Math.ceil(seconds);
    const h = Math.floor(seconds / 3600);
    const m = Math.floor(seconds % 3600 / 60);
    const s = seconds % 60;
    const pad = n => String(n).padStart(2, '0');
    return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}
