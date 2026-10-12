"""A plugin kernel for strategies: services, declared dependencies, reversible effects.

Why this exists
---------------
A strategy here used to be a function in `decision/signals.py` plus a block in a
`config/*.json`, wired by hand at each caller. Adding one, swapping its data
source, or changing its parameters meant editing the callers. This kernel is the
mounting surface that was missing: a strategy, the bars it reads and the
evaluator that scores it are each a plugin, composed by rows in
`config/strategy-plugins.json`.

The primitives are Cordis's, the ones `examples/dsh` is built on, restated in
Python because strategies have to run inside this package's data and gates:

* **fiber** — one mounted plugin: its config, the services it declared it
  needs, and every registration it made. `Kernel.plugin()` returns it.
* **provide / inject** — a plugin publishes a named service; another declares
  the names it needs. Mount order does not matter: a fiber waits until all of
  its injected services exist, and is stopped again when one is withdrawn.
* **effect** — anything a plugin registers goes through `ctx.effect()`, which
  records how to undo it. Stopping a fiber runs those disposers in reverse, so
  unmounting a plugin leaves nothing of it behind.
* **update** — a new config restarts the fiber. A parameter change is the same
  operation as unmount + mount, never a mutation of a running strategy.

* **event** — `ctx.on(event, handler)` listens, as an effect, so a stopped
  fiber hears nothing more. `ctx.emit(event, payload)` calls every listener in
  the order they registered and returns what they returned. A plugin may only
  emit the events it names in `emits`, for the reason it may only read the
  services it names in `inject`: what a plugin can set in motion is readable
  from its declaration. Dispatch is synchronous and a listener's exception
  reaches the emitter, so a listener can refuse what it is told about; it has
  no way to make the emitter do more than it was going to.

What is deliberately absent: Cordis's `waterfall` and `bail` dispatch, async
fibers and scoped service isolation. Every path that mounts plugins is one
bounded, single-threaded process, so nothing here has anything to await.
"""
from __future__ import annotations

from typing import Any, Callable

Disposer = Callable[[], None]

PENDING = 'pending'
ACTIVE = 'active'
DISPOSED = 'disposed'


class KernelError(Exception):
    """A composition error: a duplicate service, an undeclared dependency."""


class Context:
    """What a plugin's `apply(ctx, config)` is handed. Bound to one fiber."""

    def __init__(self, fiber: 'Fiber'):
        self.fiber = fiber

    def get(self, name: str) -> Any:
        """A service this plugin declared in `inject`.

        Undeclared reads are refused rather than served: a plugin that reaches
        a service it never declared would start before that service exists on
        some mount orders and keep running after it is withdrawn.
        """
        if name not in self.fiber.inject:
            raise KernelError(
                f'{self.fiber.name!r} reads service {name!r} without declaring '
                f'it in inject {sorted(self.fiber.inject)}')
        return self.fiber.kernel._services[name][0]

    def effect(self, execute: Callable[[], Disposer], label: str = '') -> Disposer:
        """Run a registration now and remember how to undo it."""
        return self.fiber._effect(execute, label)

    def provide(self, name: str, service: Any) -> Disposer:
        """Publish a service; withdrawn when this fiber stops."""
        return self.effect(lambda: self.fiber.kernel._provide(name, service, self.fiber),
                           f'provide({name})')

    def on(self, event: str, handler: Callable[[Any], Any]) -> Disposer:
        """Listen for an event until this fiber stops."""
        return self.effect(lambda: self.fiber.kernel.on(event, handler), f'on({event})')

    def emit(self, event: str, payload: Any = None) -> list:
        """Tell every listener; returns their answers in registration order."""
        if event not in self.fiber.emits:
            raise KernelError(
                f'{self.fiber.name!r} emits {event!r} without declaring it in '
                f'emits {sorted(self.fiber.emits)}')
        return self.fiber.kernel.emit(event, payload)

    def plugin(self, plugin: Any, config: dict | None = None) -> 'Fiber':
        """Mount a child plugin that lives no longer than this fiber."""
        child = self.fiber.kernel.plugin(plugin, config)
        self.effect(lambda: child.dispose, f'plugin({child.name})')
        return child


class Fiber:
    """One mounted plugin and everything it registered."""

    def __init__(self, kernel: 'Kernel', plugin: Any, config: dict | None):
        self.kernel = kernel
        self.plugin = plugin
        self.name = str(getattr(plugin, 'name', None) or getattr(plugin, '__name__', plugin))
        self.inject = tuple(getattr(plugin, 'inject', ()) or ())
        self.emits = tuple(getattr(plugin, 'emits', ()) or ())
        self.config = dict(config or {})
        self.state = PENDING
        self._effects: list[tuple[str, Disposer]] = []

    @property
    def effects(self) -> list[str]:
        """Labels of the live registrations, in the order they were made."""
        return [label for label, _ in self._effects]

    @property
    def missing(self) -> list[str]:
        return [name for name in self.inject if name not in self.kernel._services]

    def _effect(self, execute, label):
        if self.state == DISPOSED:
            raise KernelError(f'cannot create effect on disposed fiber {self.name!r}')
        entry = (label, execute())
        self._effects.append(entry)

        def dispose():
            if entry in self._effects:
                self._effects.remove(entry)
                entry[1]()
        return dispose

    def _start(self):
        if self.state != PENDING or self.missing:
            return
        self.state = ACTIVE
        try:
            self.plugin.apply(Context(self), dict(self.config))
        except BaseException:
            # A half-applied plugin is the one state unmounting cannot undo
            # later, so what it did register is rolled back before the error
            # leaves.
            self._stop()
            raise

    def _stop(self):
        while self._effects:
            self._effects.pop()[1]()
        if self.state == ACTIVE:
            self.state = PENDING

    def update(self, config: dict) -> None:
        """Replace the config and restart: stop, then start under the new one."""
        self._stop()
        self.config = dict(config or {})
        self._start()

    def dispose(self) -> None:
        self._stop()
        self.state = DISPOSED
        if self in self.kernel.fibers:
            self.kernel.fibers.remove(self)


class Kernel:
    """Holds the services and the fibers; has no behaviour of its own."""

    def __init__(self):
        self._services: dict[str, tuple[Any, Fiber]] = {}
        self._listeners: dict[str, list[Callable[[Any], Any]]] = {}
        self.fibers: list[Fiber] = []

    def plugin(self, plugin: Any, config: dict | None = None) -> Fiber:
        fiber = Fiber(self, plugin, config)
        self.fibers.append(fiber)
        try:
            fiber._start()
        except BaseException:
            fiber.dispose()
            raise
        return fiber

    def get(self, name: str) -> Any:
        """A service, for the host that mounted the plugins."""
        return self._services[name][0]

    def on(self, event: str, handler: Callable[[Any], Any]) -> Disposer:
        """Listen for an event; the returned disposer stops listening."""
        listeners = self._listeners.setdefault(event, [])
        listeners.append(handler)

        def stop():
            if handler in listeners:
                listeners.remove(handler)
        return stop

    def emit(self, event: str, payload: Any = None) -> list:
        """An event from the host that mounted the plugins.

        Synchronous: every listener has answered, or one has raised, before
        this returns.
        """
        return [handler(payload) for handler in list(self._listeners.get(event, ()))]

    def services(self) -> dict[str, str]:
        """{service name: the fiber providing it}."""
        return {name: owner.name for name, (_, owner) in self._services.items()}

    def _provide(self, name, service, owner) -> Disposer:
        if name in self._services:
            raise KernelError(
                f'service {name!r} is already provided by '
                f'{self._services[name][1].name!r}')
        self._services[name] = (service, owner)
        for fiber in list(self.fibers):
            fiber._start()

        def withdraw():
            # Dependents stop first: their disposers may still call the service.
            for fiber in list(self.fibers):
                if fiber is not owner and name in fiber.inject:
                    fiber._stop()
            del self._services[name]
        return withdraw

    def dispose(self) -> None:
        for fiber in reversed(list(self.fibers)):
            fiber.dispose()
