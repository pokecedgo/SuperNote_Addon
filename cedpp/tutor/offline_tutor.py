"""Canned tutor for `--offline` demos: matches the built-in demo notebook script."""
from __future__ import annotations

import itertools
import time

from .base import NoteTutor, Tip, TutorRequest

DEMO_TIPS = [
    Tip(False, "Calc III - Lecture 7", "Lecture heading",
        "Nice, dated headings make review week much easier.",
        ["Add today's date next to the lecture number"]),
    Tip(False, "∇f = ⟨∂f/∂x, ∂f/∂y⟩", "Gradient formula",
        "Hey, this is the gradient! It points in the direction of steepest increase of f.",
        ["|∇f| = the maximum rate of increase",
         "Directional derivative: Dᵤf = ∇f · u (u a unit vector)",
         "∇f is perpendicular to level curves f(x,y) = c"]),
    Tip(False, "f(x,y) = x²y + 3y", "Worked example setup",
        "Good example to practice partials on: treat y as a constant for ∂f/∂x.",
        ["∂f/∂x = 2xy", "∂f/∂y = x² + 3"]),
    Tip(False, "∇f = ⟨2xy, x² + 2⟩", "Check the y-component",
        "Heads up: ∂/∂y of (x²y + 3y) is x² + 3, not x² + 2.",
        ["So ∇f = ⟨2xy, x² + 3⟩"], heads_up=True),
    Tip(False, "dz/dt = fₓ·x'(t) + f_y·y'(t)", "Multivariable chain rule",
        "This is the chain rule for a path (x(t), y(t)). It's just ∇f · r'(t).",
        ["Tree diagrams help with longer chains",
         "Two parameters: ∂z/∂s = fₓ·xₛ + f_y·yₛ"]),
]


class OfflineTutor(NoteTutor):
    """No network: cycles through DEMO_TIPS with a short fake 'thinking' delay."""

    name = "offline"

    def __init__(self, delay_s: float = 1.2) -> None:
        self.delay_s = delay_s
        self._tips = itertools.cycle(DEMO_TIPS)

    def analyze(self, request: TutorRequest) -> Tip:
        time.sleep(self.delay_s)
        return next(self._tips)
